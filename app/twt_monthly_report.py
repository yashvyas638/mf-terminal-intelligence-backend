"""TWT monthly portfolio report comparison helpers.

Comparisons consume immutable report JSON only; they never revalue a portfolio.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


def _period_key(report: dict[str, Any]) -> str | None:
    valuation = report.get("valuation") or {}
    raw = valuation.get("valuation_date")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10]).strftime("%Y-%m")
    except ValueError:
        return None


def select_latest_distinct_months(
    snapshots: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Select the newest saved report for each distinct valuation month.

    Input must be ordered newest-first by generated_at and id. A second report
    from the same valuation month is not treated as a month-on-month period.
    """
    selected: dict[str, dict[str, Any]] = {}
    for snapshot in snapshots:
        report = snapshot.get("report") or {}
        period = _period_key(report)
        if period and period not in selected:
            selected[period] = {**snapshot, "period": period}
    return sorted(selected.values(), key=lambda item: item["period"], reverse=True)[:2]


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _rows(report: dict[str, Any], path: tuple[str, ...]) -> list[dict[str, Any]] | None:
    node: Any = report
    for part in path:
        node = node.get(part) if isinstance(node, dict) else None
    return node if isinstance(node, list) else None


def _compare(
    previous: list[dict[str, Any]],
    current: list[dict[str, Any]],
    *,
    key_field: str,
    value_fields: tuple[str, ...],
) -> dict[str, Any]:
    old = {str(row.get(key_field)): row for row in previous}
    new = {str(row.get(key_field)): row for row in current}
    items = []
    for key in sorted(set(old) | set(new)):
        before, after = old.get(key), new.get(key)
        metrics: dict[str, Any] = {}
        for field in value_fields:
            old_value = _decimal(before.get(field)) if before else None
            new_value = _decimal(after.get(field)) if after else None
            change = new_value - old_value if old_value is not None and new_value is not None else None
            metric = {
                "previous": str(old_value) if old_value is not None else None,
                "current": str(new_value) if new_value is not None else None,
                "change": str(change) if change is not None else None,
                "status": "COMPARABLE" if change is not None else "NOT_COMPARABLE_MISSING_SOURCE",
            }
            if field.endswith("_pct"):
                metric["change_percentage_points"] = str(change) if change is not None else None
            if field.endswith("_inr") or field in {"market_value", "lookthrough_value"}:
                metric["change_inr"] = str(change) if change is not None else None
            metrics[field] = metric
        items.append({"key": key, "metrics": metrics})
    return {"status": "COMPARABLE", "items": items}


def compare_monthly_reports(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Compare portfolio sections with explicit INR and percentage-point deltas."""
    old_report = previous["report"]
    new_report = current["report"]
    comparisons: dict[str, Any] = {}

    specs = (
        ("scheme", ("allocation_intelligence", "allocation", "schemes"), "scheme_code", ("market_value_inr", "portfolio_weight_pct")),
        ("category", ("allocation_intelligence", "allocation", "by_category"), "name", ("market_value_inr", "portfolio_weight_pct")),
        ("sub_category", ("allocation_intelligence", "allocation", "by_sub_category"), "name", ("market_value_inr", "portfolio_weight_pct")),
        ("asset_class", ("allocation_intelligence", "allocation", "by_asset_class"), "name", ("market_value_inr", "portfolio_weight_pct")),
        ("amc", ("allocation_intelligence", "amc_concentration", "amcs"), "name", ("market_value_inr", "portfolio_weight_pct")),
        ("sector", ("lookthrough", "sector_exposure"), "sector", ("lookthrough_value", "portfolio_weight_pct")),
    )
    allocation_statuses = {"AVAILABLE", "PARTIAL_STALE_NAV"}
    for name, path, key_field, value_fields in specs:
        old_rows, new_rows = _rows(old_report, path), _rows(new_report, path)
        old_status = (
            old_report.get("lookthrough", {}).get("coverage", {}).get("status")
            if name == "sector" else old_report.get("allocation_intelligence", {}).get("status")
        )
        new_status = (
            new_report.get("lookthrough", {}).get("coverage", {}).get("status")
            if name == "sector" else new_report.get("allocation_intelligence", {}).get("status")
        )
        allowed = {"COMPLETE", "PARTIAL_MISSING_DISCLOSURES", "PARTIAL_STALE_DISCLOSURES"} if name == "sector" else allocation_statuses
        if old_rows is None or new_rows is None or old_status not in allowed or new_status not in allowed:
            comparisons[name] = {"status": "WITHHELD_OR_NOT_COMPARABLE", "items": []}
        else:
            comparisons[name] = _compare(old_rows, new_rows, key_field=key_field, value_fields=value_fields)

    def market_cap_rows(report: dict[str, Any]) -> list[dict[str, Any]] | None:
        section = report.get("market_cap_intelligence") or {}
        rows = section.get("classified_distribution")
        if not isinstance(rows, list):
            return None
        result = [{"market_cap_bucket": row.get("market_cap_bucket"), "weight_of_total_portfolio_pct": row.get("weight_of_total_portfolio_pct"), "exposure_inr": row.get("exposure_inr")} for row in rows]
        result.extend({
            "market_cap_bucket": "UNCLASSIFIED:" + str(row.get("reason")),
            "weight_of_total_portfolio_pct": row.get("weight_of_total_portfolio_pct"),
            "exposure_inr": row.get("exposure_inr"),
        } for row in section.get("unclassified_exposure") or [])
        return result

    old_mc, new_mc = market_cap_rows(old_report), market_cap_rows(new_report)
    mc_allowed = {"AVAILABLE", "PARTIAL_LOOKTHROUGH_COVERAGE", "PARTIAL_CLASSIFICATION_COVERAGE", "PARTIAL_LOOKTHROUGH_AND_CLASSIFICATION_COVERAGE"}
    if old_mc is None or new_mc is None or (old_report.get("market_cap_intelligence") or {}).get("status") not in mc_allowed or (new_report.get("market_cap_intelligence") or {}).get("status") not in mc_allowed:
        comparisons["market_cap"] = {"status": "WITHHELD_OR_NOT_COMPARABLE", "items": []}
    else:
        comparisons["market_cap"] = _compare(old_mc, new_mc, key_field="market_cap_bucket", value_fields=("exposure_inr", "weight_of_total_portfolio_pct"))

    old_value = _decimal((old_report.get("valuation") or {}).get("current_value"))
    new_value = _decimal((new_report.get("valuation") or {}).get("current_value"))
    comparisons["portfolio_value"] = {
        "status": "COMPARABLE" if old_value is not None and new_value is not None else "NOT_COMPARABLE",
        "previous_inr": str(old_value) if old_value is not None else None,
        "current_inr": str(new_value) if new_value is not None else None,
        "change_inr": str(new_value - old_value) if old_value is not None and new_value is not None else None,
    }
    return {
        "status": "AVAILABLE",
        "previous_period": previous["period"],
        "current_period": current["period"],
        "previous_valuation_date": (old_report.get("valuation") or {}).get("valuation_date"),
        "current_valuation_date": (new_report.get("valuation") or {}).get("valuation_date"),
        "comparisons": comparisons,
        "limitations": [
            "The newest saved report for each distinct valuation month is compared; multiple snapshots in one month do not create a month-on-month period.",
            "INR and percentage-point changes are calculated only where both immutable snapshots contain the required source values.",
            "Look-through and market-cap changes may reflect disclosure or classification refreshes as well as portfolio trades and market movement.",
            "This is a comparison of saved monthly snapshots, not a daily time series or a causal attribution of market movement and cash flows.",
        ],
    }
