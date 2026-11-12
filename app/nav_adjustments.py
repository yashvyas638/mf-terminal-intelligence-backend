"""Verified NAV unit-scale adjustments and conservative discontinuity quality gates.

Raw AMFI observations are never modified. Adjustments are applied only to the
analytics series and are versioned in every research snapshot for auditability.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

NAV_ADJUSTMENT_REGISTRY_VERSION = "2026-11-12.1"

# ICICI Prudential Overnight Fund completed a 10x unit consolidation effective
# 17-Aug-2022. The AMC's February-2026 factsheet records NAV 100.3737 on
# 29-Jul-2022 and 1004.3319 on 30-Aug-2022 for the Monthly IDCW plan, with the
# same Rs.100 face value; its Direct Quarterly IDCW NAV similarly moves from
# 100.8649 (17-May-2022) to 1011.5232 (18-Aug-2022). ValueResearch's plan
# history records the corresponding NAV-level reset. The event applies across
# the fund's 20 AMFI plan/option codes listed below.
_ICICI_OVERNIGHT_SCHEME_CODES = (
    *range(145535, 145551),
    *range(149408, 149412),
)

_VERIFIED_EVENTS: tuple[dict[str, Any], ...] = (
    {
        "scheme_codes": frozenset(_ICICI_OVERNIGHT_SCHEME_CODES),
        "effective_date": date(2022, 8, 17),
        "factor": 10.0,
        "action": "unit_consolidation",
        "source_urls": (
            "https://digitalfactsheet.icicipruamc.com/fact/pdf/fund-factsheet-for-february-2026.pdf",
            "https://www.valueresearchonline.com/funds/38261/icici-prudential-overnight-fund-direct-plan/",
        ),
        "source_note": (
            "ICICI Prudential AMC factsheet records the pre/post NAV level "
            "change across Overnight Fund options; ValueResearch history "
            "corroborates the 17-Aug-2022 level reset. Pre-event NAVs are "
            "expressed in post-consolidation units by multiplying by 10."
        ),
    },
)

_PERIOD_DAYS = {
    "1M": 30,
    "3M": 90,
    "6M": 182,
    "1Y": 365,
    "3Y": 365 * 3,
    "5Y": 365 * 5,
}


def apply_verified_nav_adjustments(
    scheme_code: int,
    points: Iterable[tuple[date, float]],
) -> tuple[list[tuple[date, float]], list[dict[str, Any]]]:
    """Apply verified scale changes to pre-event NAVs without mutating source rows."""
    rows = [(observed_date, float(value)) for observed_date, value in points]
    events = [
        event for event in _VERIFIED_EVENTS
        if scheme_code in event["scheme_codes"]
        and any(d < event["effective_date"] for d, _ in rows)
        and any(d >= event["effective_date"] for d, _ in rows)
    ]
    adjusted: list[tuple[date, float]] = []
    for observed_date, value in rows:
        factor = 1.0
        for event in events:
            if observed_date < event["effective_date"]:
                factor *= event["factor"]
        adjusted.append((observed_date, value * factor))
    applied = [
        {
            "action": event["action"],
            "effective_date": event["effective_date"].isoformat(),
            "factor": event["factor"],
            "source_urls": list(event["source_urls"]),
            "source_note": event["source_note"],
        }
        for event in events
    ]
    return adjusted, applied


def detect_nav_discontinuities(
    points: Iterable[tuple[date, float]],
    *,
    ratio_threshold: float = 2.0,
    max_gap_days: int = 45,
) -> list[dict[str, Any]]:
    """Find unverified NAV level jumps; never auto-adjust a source observation."""
    rows = list(points)
    flags: list[dict[str, Any]] = []
    for (previous_date, previous_value), (observed_date, value) in zip(rows, rows[1:]):
        gap_days = (observed_date - previous_date).days
        if gap_days <= 0 or gap_days > max_gap_days or previous_value <= 0:
            continue
        ratio = value / previous_value
        if ratio >= ratio_threshold or ratio <= 1.0 / ratio_threshold:
            flags.append(
                {
                    "type": "unverified_nav_level_discontinuity",
                    "previous_date": previous_date,
                    "nav_date": observed_date,
                    "previous_nav": float(previous_value),
                    "nav_value": float(value),
                    "ratio": float(ratio),
                    "gap_days": gap_days,
                }
            )
    return flags


def apply_nav_quality_gates(
    metrics: dict[str, Any],
    *,
    latest_date: date,
    window_days: int,
    discontinuities: list[dict[str, Any]],
) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    """Suppress only period/window metrics crossed by an unverified NAV jump."""
    periods = dict(metrics.get("period_returns") or {})
    affected_periods: dict[str, list[dict[str, Any]]] = {}
    for label, days in _PERIOD_DAYS.items():
        target_date = latest_date - timedelta(days=days)
        events = [event for event in discontinuities if event["nav_date"] > target_date]
        if events:
            periods[label] = None
            affected_periods[label] = events

    window_start = latest_date - timedelta(days=window_days)
    window_events = [
        event for event in discontinuities if event["nav_date"] >= window_start
    ]
    if window_events:
        for key in (
            "total_return",
            "cagr",
            "annualized_volatility",
            "sharpe_ratio",
            "sortino_ratio",
            "max_drawdown",
            "positive_month_rate",
        ):
            metrics[key] = None
        metrics["rolling_1y"] = {
            "status": "REVIEW_REQUIRED",
            "observations": 0,
            "positive_window_rate": None,
        }
        event_months = {event["nav_date"].strftime("%Y-%m") for event in window_events}
        metrics["monthly_returns"] = [
            item
            for item in metrics.get("monthly_returns", [])
            if item.get("month") not in event_months
        ]

    metrics["period_returns"] = periods
    relevant_events = {
        (event["previous_date"], event["nav_date"]): event
        for events in affected_periods.values()
        for event in events
    }
    for event in window_events:
        relevant_events[(event["previous_date"], event["nav_date"])] = event

    quality_flags: list[dict[str, Any]] = []
    for event in relevant_events.values():
        affected = [
            label for label, events in affected_periods.items() if event in events
        ]
        quality_flags.append(
            {
                "type": event["type"],
                "previous_date": event["previous_date"].isoformat(),
                "nav_date": event["nav_date"].isoformat(),
                "previous_nav": event["previous_nav"],
                "nav_value": event["nav_value"],
                "ratio": event["ratio"],
                "gap_days": event["gap_days"],
                "affected_periods": affected,
                "affects_window_metrics": event in window_events,
            }
        )

    return metrics, "REVIEW_REQUIRED" if quality_flags else "PASS", quality_flags
