"""TWT monthly portfolio report comparison helpers.

Comparisons consume immutable report JSON only; they never revalue a portfolio.
"""
from __future__ import annotations

from calendar import monthrange
import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


def is_month_end_valuation_date(raw: Any, *, window_days: int = 7) -> bool:
    """Return whether a valuation date falls within the final days of its month."""
    if not raw or window_days < 1:
        return False
    try:
        valuation_date = date.fromisoformat(str(raw)[:10])
    except ValueError:
        return False
    month_end = date(
        valuation_date.year,
        valuation_date.month,
        monthrange(valuation_date.year, valuation_date.month)[1],
    )
    # A seven-calendar-day window contains seven dates, including month-end.
    return 0 <= (month_end - valuation_date).days < window_days


def _period_key(report: dict[str, Any]) -> str | None:
    valuation = report.get("valuation") or {}
    raw = valuation.get("valuation_date")
    if not is_month_end_valuation_date(raw):
        return None
    return str(raw)[:7]


def decode_verified_snapshot(content_json: str, expected_sha256: str) -> dict[str, Any] | None:
    """Decode immutable snapshot JSON only when its stored integrity hash matches."""
    if not isinstance(content_json, str) or not isinstance(expected_sha256, str):
        return None
    actual_sha256 = hashlib.sha256(content_json.encode("utf-8")).hexdigest()
    if actual_sha256 != expected_sha256:
        return None
    try:
        payload = json.loads(content_json)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


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
    ordered = sorted(selected.values(), key=lambda item: item["period"], reverse=True)[:2]
    if len(ordered) == 2:
        latest_month = date.fromisoformat(ordered[0]["period"] + "-01")
        previous_month = date.fromisoformat(ordered[1]["period"] + "-01")
        expected_previous = (
            date(latest_month.year - 1, 12, 1)
            if latest_month.month == 1
            else date(latest_month.year, latest_month.month - 1, 1)
        )
        # Do not label a multi-month gap as month-on-month movement.
        if previous_month != expected_previous:
            return ordered[:1]
    return ordered


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
    def keyed(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]] | None:
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                return None
            raw_key = row.get(key_field)
            if raw_key is None or not str(raw_key).strip():
                return None
            key = str(raw_key).strip()
            if key in result:
                return None
            result[key] = row
        return result

    old, new = keyed(previous), keyed(current)
    if old is None or new is None:
        return {
            "status": "WITHHELD_DUPLICATE_OR_INVALID_KEYS",
            "items": [],
            "reason": "Monthly comparison requires unique, non-empty identifiers in both immutable snapshots.",
        }
    items = []
    for key in sorted(set(old) | set(new)):
        before, after = old.get(key), new.get(key)
        metrics: dict[str, Any] = {}
        for field in value_fields:
            old_value = _decimal(before.get(field)) if before else None
            new_value = _decimal(after.get(field)) if after else None
            is_percentage = field.endswith("_pct") or "_pct_" in field
            is_inr = field.endswith("_inr") or field in {"market_value", "lookthrough_value"}
            invalid_percentage = is_percentage and any(
                value is not None and not Decimal("0") <= value <= Decimal("100")
                for value in (old_value, new_value)
            )
            invalid_amount = is_inr and any(
                value is not None and value < Decimal("0")
                for value in (old_value, new_value)
            )
            if invalid_percentage or invalid_amount:
                old_value = new_value = None
            change = new_value - old_value if old_value is not None and new_value is not None else None
            metric = {
                "previous": str(old_value) if old_value is not None else None,
                "current": str(new_value) if new_value is not None else None,
                "change": str(change) if change is not None else None,
                "status": (
                    "WITHHELD_INVALID_SOURCE_VALUE" if invalid_percentage or invalid_amount
                    else "COMPARABLE" if change is not None
                    else "NOT_COMPARABLE_MISSING_SOURCE"
                ),
            }
            if field.endswith("_pct") or "_pct_" in field:
                metric["change_percentage_points"] = str(change) if change is not None else None
            if field.endswith("_inr") or field in {"market_value", "lookthrough_value"}:
                metric["change_inr"] = str(change) if change is not None else None
            metrics[field] = metric
        items.append({
            "key": key,
            "presence_status": "NEW" if before is None else "EXITED" if after is None else "CONTINUING",
            "metrics": metrics,
        })
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
            (old_report.get("lookthrough") or {}).get("coverage", {}).get("status")
            if name == "sector" else (old_report.get("allocation_intelligence") or {}).get("status")
        )
        new_status = (
            (new_report.get("lookthrough") or {}).get("coverage", {}).get("status")
            if name == "sector" else (new_report.get("allocation_intelligence") or {}).get("status")
        )
        allowed = {"COMPLETE", "PARTIAL_MISSING_DISCLOSURES", "PARTIAL_STALE_DISCLOSURES"} if name == "sector" else allocation_statuses
        if old_rows is None or new_rows is None or old_status not in allowed or new_status not in allowed:
            comparisons[name] = {"status": "WITHHELD_OR_NOT_COMPARABLE", "items": []}
        else:
            comparisons[name] = _compare(old_rows, new_rows, key_field=key_field, value_fields=value_fields)

    def market_cap_rows(report: dict[str, Any]) -> list[dict[str, Any]] | None:
        section = report.get("market_cap_intelligence") or {}
        rows = section.get("classified_distribution")
        unclassified = section.get("unclassified_exposure") or []
        if not isinstance(rows, list) or not isinstance(unclassified, list):
            return None
        if any(not isinstance(row, dict) for row in [*rows, *unclassified]):
            return None
        result = [
            {
                "market_cap_bucket": row.get("market_cap_bucket"),
                "weight_of_total_portfolio_pct": row.get("weight_of_total_portfolio_pct"),
                "exposure_inr": row.get("exposure_inr"),
            }
            for row in rows
        ]
        result.extend({
            "market_cap_bucket": "UNCLASSIFIED:" + str(row.get("reason")),
            "weight_of_total_portfolio_pct": row.get("weight_of_total_portfolio_pct"),
            "exposure_inr": row.get("exposure_inr"),
        } for row in unclassified)
        return result

    old_mc, new_mc = market_cap_rows(old_report), market_cap_rows(new_report)
    mc_allowed = {"AVAILABLE", "PARTIAL_LOOKTHROUGH_COVERAGE", "PARTIAL_CLASSIFICATION_COVERAGE", "PARTIAL_LOOKTHROUGH_AND_CLASSIFICATION_COVERAGE"}
    if old_mc is None or new_mc is None or (old_report.get("market_cap_intelligence") or {}).get("status") not in mc_allowed or (new_report.get("market_cap_intelligence") or {}).get("status") not in mc_allowed:
        comparisons["market_cap"] = {"status": "WITHHELD_OR_NOT_COMPARABLE", "items": []}
    else:
        comparisons["market_cap"] = _compare(old_mc, new_mc, key_field="market_cap_bucket", value_fields=("exposure_inr", "weight_of_total_portfolio_pct"))

    # Target drift is comparable only when the exact same immutable policy
    # version applies in both months. A changed policy is not portfolio drift.
    def target_drift_rows(report: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
        policies = (report.get("target_policy_snapshot") or {}).get("dimensions")
        snapshots = report.get("target_drift_snapshot")
        if not isinstance(policies, list) or not isinstance(snapshots, dict):
            return None
        policy_by_dimension: dict[str, dict[str, Any]] = {}
        supported_dimensions = {"ASSET_CLASS", "CATEGORY", "SUB_CATEGORY", "AMC", "SCHEME"}
        for policy in policies:
            if not isinstance(policy, dict):
                return None
            dimension = str(policy.get("dimension") or "").strip()
            if not dimension:
                return None
            if dimension not in supported_dimensions:
                continue
            if dimension in policy_by_dimension:
                return None
            policy_by_dimension[dimension] = policy
        if set(snapshots) != set(policy_by_dimension):
            return None
        result: dict[str, dict[str, Any]] = {}
        for dimension, drift in snapshots.items():
            if not isinstance(drift, dict) or drift.get("status") != "AVAILABLE":
                return None
            policy = policy_by_dimension.get(dimension)
            version = drift.get("target_version")
            effective_from = drift.get("effective_from")
            if (not policy or version is None or effective_from is None
                    or str(policy.get("version")) != str(version)
                    or str(policy.get("effective_from")) != str(effective_from)):
                return None
            targets = drift.get("targets")
            if not isinstance(targets, list) or not targets:
                return None
            policy_targets = policy.get("targets")
            if not isinstance(policy_targets, list) or not policy_targets:
                return None
            policy_keys = {
                str(item.get("key") or "").strip()
                for item in policy_targets if isinstance(item, dict)
            }
            if len(policy_keys) != len(policy_targets) or "" in policy_keys:
                return None
            seen: set[str] = set()
            weight_total = Decimal("0")
            preferred_total = Decimal("0")
            for target in targets:
                if not isinstance(target, dict):
                    return None
                key = str(target.get("key") or "").strip()
                actual = _decimal(target.get("actual_weight_pct"))
                target_pct = _decimal(target.get("target_pct"))
                drift_pp = _decimal(target.get("drift_percentage_points"))
                if (not key or key in seen or actual is None or target_pct is None or drift_pp is None
                        or not Decimal("0") <= actual <= Decimal("100")
                        or not Decimal("0") <= target_pct <= Decimal("100")
                        or not Decimal("-100") <= drift_pp <= Decimal("100")
                        or abs((actual - target_pct) - drift_pp) > Decimal("0.05")):
                    return None
                seen.add(key)
                weight_total += actual
                preferred_total += target_pct
                result[f"{dimension}:{key}"] = {
                    "key": f"{dimension}:{key}",
                    "actual_weight_pct": str(actual),
                    "drift_percentage_points": str(drift_pp),
                }
            if (seen != policy_keys or abs(weight_total - Decimal("100")) > Decimal("0.05")
                    or abs(preferred_total - Decimal("100")) > Decimal("0.05")):
                return None
        return result if result else None

    old_target_rows = target_drift_rows(old_report)
    new_target_rows = target_drift_rows(new_report)
    if old_target_rows is None or new_target_rows is None:
        comparisons["target_drift"] = {
            "status": "WITHHELD_POLICY_VERSION_OR_SOURCE_MISMATCH",
            "items": [],
            "reason": "Target drift requires complete, reconciled snapshots under the same immutable policy version and effective date.",
        }
    elif set(old_target_rows) != set(new_target_rows):
        comparisons["target_drift"] = {
            "status": "WITHHELD_TARGET_SET_CHANGED",
            "items": [],
            "reason": "Target bucket identities changed between snapshots; policy drift cannot be isolated from allocation movement.",
        }
    else:
        target_comparison = _compare(
            list(old_target_rows.values()), list(new_target_rows.values()),
            key_field="key", value_fields=("actual_weight_pct", "drift_percentage_points"),
        )
        for item in target_comparison.get("items", []):
            metrics = item.get("metrics") or {}
            drift_metric = metrics.get("drift_percentage_points") or {}
            drift_metric["change_percentage_points"] = drift_metric.get("change")
        comparisons["target_drift"] = target_comparison

    old_value = _decimal((old_report.get("valuation") or {}).get("current_value"))
    new_value = _decimal((new_report.get("valuation") or {}).get("current_value"))
    invalid_portfolio_value = any(
        value is not None and value < Decimal("0")
        for value in (old_value, new_value)
    )
    value_comparable = old_value is not None and new_value is not None and not invalid_portfolio_value
    comparisons["portfolio_value"] = {
        "status": "WITHHELD_INVALID_SOURCE_VALUE" if invalid_portfolio_value else "COMPARABLE" if value_comparable else "NOT_COMPARABLE",
        "previous_inr": str(old_value) if value_comparable else None,
        "current_inr": str(new_value) if value_comparable else None,
        "change_inr": str(new_value - old_value) if value_comparable else None,
    }

    old_amc = (old_report.get("allocation_intelligence") or {}).get("amc_concentration") or {}
    new_amc = (new_report.get("allocation_intelligence") or {}).get("amc_concentration") or {}
    amc_metrics = {}
    allocation_comparable = (
        (old_report.get("allocation_intelligence") or {}).get("status") in allocation_statuses
        and (new_report.get("allocation_intelligence") or {}).get("status") in allocation_statuses
    )
    amc_bounds = {
        "top_1_amc_weight_pct": (Decimal("0"), Decimal("100")),
        "top_3_amc_weight_pct": (Decimal("0"), Decimal("100")),
        "top_5_amc_weight_pct": (Decimal("0"), Decimal("100")),
        "hhi_points": (Decimal("0"), Decimal("10000")),
        "effective_amc_count": (Decimal("0"), None),
    }

    def amc_snapshot_is_consistent(metrics: dict[str, Any]) -> bool:
        values = {name: _decimal(metrics.get(name)) for name in amc_bounds}
        for name, value in values.items():
            minimum, maximum = amc_bounds[name]
            if value is not None and (
                value < minimum or (maximum is not None and value > maximum)
            ):
                return False
        top_1 = values["top_1_amc_weight_pct"]
        top_3 = values["top_3_amc_weight_pct"]
        top_5 = values["top_5_amc_weight_pct"]
        if top_1 is not None and top_3 is not None and top_1 > top_3:
            return False
        if top_3 is not None and top_5 is not None and top_3 > top_5:
            return False
        hhi = values["hhi_points"]
        effective_count = values["effective_amc_count"]
        # For a populated portfolio, effective AMC count is 10,000 / HHI.
        # Allow a small tolerance for source rounding; the all-zero case is
        # retained for an empty/unvalued allocation snapshot.
        if hhi is not None and effective_count is not None:
            if hhi > 0 and effective_count > 0:
                return abs(hhi * effective_count - Decimal("10000")) <= Decimal("0.5")
            return hhi == 0 and effective_count == 0
        return True  # Missing evidence is withheld per metric, not invented.

    invalid_amc_snapshot = not (
        amc_snapshot_is_consistent(old_amc) and amc_snapshot_is_consistent(new_amc)
    )
    for metric_name, (minimum, maximum) in amc_bounds.items():
        old_metric = _decimal(old_amc.get(metric_name))
        new_metric = _decimal(new_amc.get(metric_name))
        invalid = invalid_amc_snapshot or any(
            value is not None and (value < minimum or (maximum is not None and value > maximum))
            for value in (old_metric, new_metric)
        )
        comparable = allocation_comparable and not invalid and old_metric is not None and new_metric is not None
        delta = new_metric - old_metric if comparable else None
        amc_metrics[metric_name] = {
            "previous": str(old_metric) if comparable else None,
            "current": str(new_metric) if comparable else None,
            "change": str(delta) if delta is not None else None,
            "change_percentage_points": str(delta) if delta is not None and metric_name.endswith("_pct") else None,
            "status": (
                "WITHHELD_INVALID_SOURCE_VALUE" if invalid
                else "COMPARABLE" if comparable
                else "WITHHELD_OR_NOT_COMPARABLE"
            ),
        }
    comparisons["amc_concentration_metrics"] = amc_metrics

    def coverage_delta(name: str, old_value: Any, new_value: Any) -> dict[str, Any]:
        old_number, new_number = _decimal(old_value), _decimal(new_value)
        invalid = any(
            value is not None and not Decimal("0") <= value <= Decimal("100")
            for value in (old_number, new_number)
        )
        if invalid:
            old_number = new_number = None
        delta = new_number - old_number if old_number is not None and new_number is not None else None
        return {
            "previous_pct": str(old_number) if old_number is not None else None,
            "current_pct": str(new_number) if new_number is not None else None,
            "change_percentage_points": str(delta) if delta is not None else None,
            "status": "WITHHELD_INVALID_SOURCE_VALUE" if invalid else "COMPARABLE" if delta is not None else "COVERAGE_NOT_REPORTED",
        }

    old_allocation_evidence = (old_report.get("allocation_intelligence") or {}).get("evidence") or {}
    new_allocation_evidence = (new_report.get("allocation_intelligence") or {}).get("evidence") or {}
    old_nav_coverage = old_allocation_evidence.get("nav_coverage") or {}
    new_nav_coverage = new_allocation_evidence.get("nav_coverage") or {}
    old_lookthrough_coverage = (old_report.get("lookthrough") or {}).get("coverage") or {}
    new_lookthrough_coverage = (new_report.get("lookthrough") or {}).get("coverage") or {}
    old_market_cap = old_report.get("market_cap_intelligence") or {}
    new_market_cap = new_report.get("market_cap_intelligence") or {}
    old_overlap = old_report.get("overlap_intelligence") or {}
    new_overlap = new_report.get("overlap_intelligence") or {}
    old_disclosure_health = old_overlap.get("disclosure_health") or {}
    new_disclosure_health = new_overlap.get("disclosure_health") or {}
    coverage_comparison = {
        "fresh_nav_weight": coverage_delta("fresh_nav_weight", old_nav_coverage.get("fresh_nav_coverage_pct"), new_nav_coverage.get("fresh_nav_coverage_pct")),
        "fresh_holdings_weight": coverage_delta("fresh_holdings_weight", old_lookthrough_coverage.get("fresh_covered_weight_pct"), new_lookthrough_coverage.get("fresh_covered_weight_pct")),
        "market_cap_classification": coverage_delta("market_cap_classification", old_market_cap.get("classified_coverage_of_positive_lookthrough_pct"), new_market_cap.get("classified_coverage_of_positive_lookthrough_pct")),
        "overlap_scheme_disclosure": coverage_delta("overlap_scheme_disclosure", old_disclosure_health.get("disclosure_scheme_coverage_pct"), new_disclosure_health.get("disclosure_scheme_coverage_pct")),
    }
    comparisons["data_coverage"] = coverage_comparison

    def normalized_overlap_pairs(rows: Any) -> list[dict[str, Any]] | None:
        if not isinstance(rows, list):
            return None
        normalized_pairs = []
        for row in rows:
            if not isinstance(row, dict):
                return None
            scheme_a = str(row.get("scheme_a") or "").strip()
            scheme_b = str(row.get("scheme_b") or "").strip()
            if not scheme_a or not scheme_b or scheme_a == scheme_b:
                return None
            pair = dict(row)
            if scheme_a > scheme_b:
                scheme_a, scheme_b = scheme_b, scheme_a
                pair["overlap_pct_of_scheme_a_nav"], pair["overlap_pct_of_scheme_b_nav"] = (
                    pair.get("overlap_pct_of_scheme_b_nav"),
                    pair.get("overlap_pct_of_scheme_a_nav"),
                )
            pair["scheme_a"] = scheme_a
            pair["scheme_b"] = scheme_b
            pair["pair_key"] = scheme_a + ":" + scheme_b
            normalized_pairs.append(pair)
        if len({row["pair_key"] for row in normalized_pairs}) != len(normalized_pairs):
            return None
        return normalized_pairs

    old_pairs = normalized_overlap_pairs(old_overlap.get("pairs"))
    new_pairs = normalized_overlap_pairs(new_overlap.get("pairs"))
    if old_overlap.get("status") == "AVAILABLE" and new_overlap.get("status") == "AVAILABLE" and old_pairs is not None and new_pairs is not None:
        comparisons["overlap_pairs"] = _compare(
            old_pairs,
            new_pairs,
            key_field="pair_key",
            value_fields=("overlap_inr", "overlap_pct_of_scheme_a_nav", "overlap_pct_of_scheme_b_nav"),
        )
    else:
        comparisons["overlap_pairs"] = {"status": "WITHHELD_OR_PARTIAL_DISCLOSURE_COVERAGE", "items": []}
    old_dup = old_overlap.get("portfolio_duplication") or {}
    new_dup = new_overlap.get("portfolio_duplication") or {}
    old_dup_value = _decimal(old_dup.get("duplicated_exposure_inr"))
    new_dup_value = _decimal(new_dup.get("duplicated_exposure_inr"))
    if old_overlap.get("status") == "AVAILABLE" and new_overlap.get("status") == "AVAILABLE" and old_dup_value is not None and new_dup_value is not None:
        comparisons["portfolio_duplication"] = {
            "status": "COMPARABLE",
            "previous_inr": str(old_dup_value),
            "current_inr": str(new_dup_value),
            "change_inr": str(new_dup_value - old_dup_value),
        }
    else:
        comparisons["portfolio_duplication"] = {
            "status": "WITHHELD_OR_PARTIAL_DISCLOSURE_COVERAGE",
            "previous_inr": None,
            "current_inr": None,
            "change_inr": None,
        }

    old_risk = old_report.get("risk") or {}
    new_risk = new_report.get("risk") or {}
    old_risk_window = old_report.get("lookback_days")
    new_risk_window = new_report.get("lookback_days")
    if (old_risk_window != new_risk_window or isinstance(old_risk_window, bool)
            or not isinstance(old_risk_window, int) or old_risk_window <= 0):
        risk_withheld_status = "WITHHELD_DIFFERENT_OR_MISSING_LOOKBACK"
    elif old_risk.get("status") != "OK" or new_risk.get("status") != "OK":
        risk_withheld_status = "WITHHELD_RISK_INPUT_STATUS"
    else:
        risk_withheld_status = None

    risk_changes = {}
    risk_bounds = {
        "annualized_volatility": (Decimal("0"), None),
        "max_drawdown": (Decimal("-1"), Decimal("0")),
        "historical_var_95": (Decimal("0"), Decimal("1")),
        "historical_cvar_95": (Decimal("0"), Decimal("1")),
    }
    old_risk_metrics = old_risk.get("metrics") if isinstance(old_risk.get("metrics"), dict) else old_risk
    new_risk_metrics = new_risk.get("metrics") if isinstance(new_risk.get("metrics"), dict) else new_risk
    for metric_name, (minimum, maximum) in risk_bounds.items():
        # The report API stores portfolio_risk_metrics output under risk.metrics.
        # Direct metric fields are accepted as a compatibility fallback.
        old_metric = _decimal(old_risk_metrics.get(metric_name))
        new_metric = _decimal(new_risk_metrics.get(metric_name))
        invalid_metric = any(
            value is not None and (value < minimum or (maximum is not None and value > maximum))
            for value in (old_metric, new_metric)
        )
        comparable = risk_withheld_status is None and not invalid_metric and old_metric is not None and new_metric is not None
        risk_changes[metric_name] = {
            "previous": str(old_metric) if comparable else None,
            "current": str(new_metric) if comparable else None,
            "change": str(new_metric - old_metric) if comparable else None,
            "status": (
                "WITHHELD_INVALID_SOURCE_VALUE" if invalid_metric
                else "COMPARABLE" if comparable
                else risk_withheld_status or "WITHHELD_METRIC_UNAVAILABLE"
            ),
            "lookback_days": old_risk_window if comparable else None,
        }
    return {
        "status": "AVAILABLE",
        "previous_period": previous["period"],
        "current_period": current["period"],
        "previous_valuation_date": (old_report.get("valuation") or {}).get("valuation_date"),
        "current_valuation_date": (new_report.get("valuation") or {}).get("valuation_date"),
        "comparisons": comparisons,
        "risk_changes": risk_changes,
        "limitations": [
            "The newest saved report for each distinct valuation month is compared; multiple snapshots in one month do not create a month-on-month period.",
            "INR and percentage-point changes are calculated only where both immutable snapshots contain the required source values.",
            "Look-through and market-cap changes may reflect disclosure or classification refreshes as well as portfolio trades and market movement.",
            "This is a comparison of saved monthly snapshots, not a daily time series or a causal attribution of market movement and cash flows.",
        ],
    }
