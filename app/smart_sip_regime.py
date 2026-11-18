"""Evidence-gated Smart SIP regime assessment.

Separates portfolio need from market opportunity. Non-executing: it never
changes a SIP and never manufactures missing signals. Benchmark observations
must be verified TRI values with provenance supplied by the caller.
"""
from __future__ import annotations
from datetime import date
from math import sqrt
from statistics import pstdev
from typing import Any, Iterable, Mapping

ENGINE_VERSION = "smart-sip-regime-v1.0.0"


def _as_date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def assess_smart_sip_regime(
    observations: Iterable[Mapping[str, Any]], *, as_of: date,
    portfolio_need: Mapping[str, Any], risk_budget: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Return explainable signals; never execute or alter planned SIPs."""
    required = {
        "max_observation_age_days", "min_observations_52w",
        "min_observations_3y", "drawdown_topup_threshold_pct",
        "momentum_floor_pct", "volatility_ceiling_pct", "annualisation_days",
    }
    missing = sorted(required - set(config))
    if missing:
        raise ValueError("missing regime config: " + ", ".join(missing))

    accepted, rejected = [], 0
    for item in observations:
        try:
            day, tri = _as_date(item["date"]), float(item["tri"])
        except (KeyError, TypeError, ValueError):
            rejected += 1
            continue
        if (item.get("source_verified") is not True or not item.get("source_id")
                or not item.get("source_hash") or tri <= 0 or day > as_of):
            rejected += 1
            continue
        accepted.append((day, tri, item))
    accepted.sort(key=lambda row: row[0])
    counts = {}
    for row in accepted:
        counts[row[0]] = counts.get(row[0], 0) + 1
    duplicates = sum(count - 1 for count in counts.values())
    clean = [row for row in accepted if counts[row[0]] == 1]
    latest = clean[-1] if clean else None
    age = (as_of - latest[0]).days if latest else None
    result = {
        "engine_version": ENGINE_VERSION, "as_of": as_of.isoformat(),
        "status": "NOT_ASSESSED", "portfolio_need": dict(portfolio_need),
        "risk_budget": dict(risk_budget),
        "market_opportunity": {"status": "NOT_ASSESSED"},
        "decision": "CONTINUE_PLANNED_SIP", "topup_eligible": False,
        "signals": {},
        "evidence": {
            "verified_observation_count": len(clean),
            "rejected_observation_count": rejected,
            "duplicate_date_count": duplicates,
            "latest_observation_date": latest[0].isoformat() if latest else None,
            "latest_observation_age_days": age,
            "source_ids": sorted({str(row[2]["source_id"]) for row in clean}),
            "source_hashes": sorted({str(row[2]["source_hash"]) for row in clean}),
        },
        "limitations": [
            "Benchmark TRI regime is not a forecast or a valuation signal.",
            "A top-up remains a user decision; no SIP is modified or executed.",
        ],
    }
    if not latest or age is None or age > int(config["max_observation_age_days"]):
        result["market_opportunity"]["reason"] = "NO_VERIFIED_FRESH_BENCHMARK_TRI"
        result["limitations"].append("Market regime withheld because benchmark TRI evidence is missing or stale.")
        return result

    latest_day, latest_tri, _ = latest
    series = [(day, value) for day, value, _ in clean]

    def window(days: int):
        cutoff = date.fromordinal(latest_day.toordinal() - days)
        return [point for point in series if point[0] >= cutoff]

    w52, w3y = window(365), window(1095)
    result["evidence"].update({"observations_52w": len(w52), "observations_3y": len(w3y)})
    if len(w52) < int(config["min_observations_52w"]) or len(w3y) < int(config["min_observations_3y"]):
        result["market_opportunity"]["reason"] = "INSUFFICIENT_HISTORY"
        result["limitations"].append("Insufficient dated TRI history for configured lookback windows.")
        return result

    drawdown = lambda points: (latest_tri / max(value for _, value in points) - 1) * 100

    def momentum(days: int):
        cutoff = date.fromordinal(latest_day.toordinal() - days)
        prior = [point for point in series if point[0] <= cutoff]
        return (latest_tri / prior[-1][1] - 1) * 100 if prior else None

    recent = window(90)
    returns = [recent[i][1] / recent[i - 1][1] - 1
               for i in range(1, len(recent)) if recent[i - 1][1] > 0]
    volatility = (pstdev(returns) * sqrt(float(config["annualisation_days"])) * 100
                  if len(returns) >= 20 else None)
    dd52, dd3y, mom63, mom126 = drawdown(w52), drawdown(w3y), momentum(63), momentum(126)
    result["signals"] = {
        "drawdown_52w_pct": round(dd52, 4), "drawdown_3y_pct": round(dd3y, 4),
        "momentum_63d_pct": round(mom63, 4) if mom63 is not None else None,
        "momentum_126d_pct": round(mom126, 4) if mom126 is not None else None,
        "annualised_volatility_90d_pct": round(volatility, 4) if volatility is not None else None,
        "observations_52w": len(w52), "observations_3y": len(w3y),
    }
    if mom63 is None or mom126 is None or volatility is None:
        result["market_opportunity"]["reason"] = "INSUFFICIENT_SIGNAL_HISTORY"
        result["limitations"].append("Momentum or volatility signal could not be calculated.")
        return result

    checks = {
        "drawdown_trigger": min(dd52, dd3y) <= -abs(float(config["drawdown_topup_threshold_pct"])),
        "momentum_floor_met": mom63 >= float(config["momentum_floor_pct"]) and mom126 >= float(config["momentum_floor_pct"]),
        "volatility_ceiling_met": volatility <= float(config["volatility_ceiling_pct"]),
    }
    market_ok = all(checks.values())
    result["market_opportunity"] = {
        "status": "ELIGIBLE" if market_ok else "NOT_ELIGIBLE",
        "checks": checks,
        "reason": "ALL_CONFIGURED_MARKET_GATES_MET" if market_ok else "ONE_OR_MORE_MARKET_GATES_NOT_MET",
    }
    need_ok = portfolio_need.get("status") == "UNDERWEIGHT" and portfolio_need.get("verified") is True
    budget_ok = risk_budget.get("allowed") is True
    result["topup_eligible"] = bool(market_ok and need_ok and budget_ok)
    result["decision"] = "TOPUP_PREVIEW_ELIGIBLE" if result["topup_eligible"] else "CONTINUE_PLANNED_SIP"
    result["status"] = "AVAILABLE"
    if not need_ok:
        result["limitations"].append("Portfolio need is not verified as underweight.")
    if not budget_ok:
        result["limitations"].append("Risk budget is not explicitly approved for an additional contribution.")
    return result
