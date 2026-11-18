"""Portfolio-level allocation, AMC concentration and holdings-overlap calculations.

Pure Decimal-based calculations. Inputs must come from current, owner-scoped
portfolio valuations and VERIFIED dated fund disclosures. This module does not
fetch data, infer classifications, or turn missing inputs into zero coverage.
"""
from __future__ import annotations

from collections import defaultdict
import csv
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Mapping
from io import StringIO

METHODOLOGY_VERSION = "portfolio-allocation-v1.0.0"
ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{10}$")
CENT = Decimal("0.01")
FOUR_DP = Decimal("0.0001")
ZERO = Decimal("0")
HUNDRED = Decimal("100")


def _d(value: Any, field: str, *, allow_none: bool = False) -> Decimal | None:
    if value is None and allow_none:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be a finite decimal")
    return result


def _pct(value: Decimal, denominator: Decimal) -> str | None:
    if denominator <= ZERO:
        return None
    return str((value / denominator * HUNDRED).quantize(FOUR_DP, rounding=ROUND_HALF_UP))


def _money(value: Decimal) -> str:
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def _hhi(values: Iterable[Decimal]) -> tuple[str | None, str | None]:
    amounts = [value for value in values if value > ZERO]
    total = sum(amounts, ZERO)
    if total <= ZERO:
        return None, None
    hhi = sum(((value / total) ** 2 for value in amounts), ZERO)
    effective = Decimal(1) / hhi
    return (
        str((hhi * Decimal(10000)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        str(effective.quantize(FOUR_DP, rounding=ROUND_HALF_UP)),
    )


def portfolio_allocation(schemes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate current scheme market values by scheme, category, asset class and AMC.

    Required fields: scheme_code, scheme_name, market_value_inr, amc.
    Optional category_group, sub_category, asset_class. Missing classifications
    remain explicitly unclassified; they are not inferred from fund names.
    """
    rows = list(schemes)
    if not rows:
        raise ValueError("at least one valued scheme is required")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        code = str(row.get("scheme_code", "")).strip()
        if not code or code in seen:
            raise ValueError("scheme_code must be present and unique")
        seen.add(code)
        value = _d(row.get("market_value_inr"), "market_value_inr")
        assert value is not None
        if value < ZERO:
            raise ValueError("scheme market value cannot be negative")
        normalized.append({
            "scheme_code": code,
            "scheme_name": str(row.get("scheme_name") or code),
            "market_value_inr": value,
            "amc": str(row.get("amc") or "UNCLASSIFIED"),
            "category_group": str(row.get("category_group") or "UNCLASSIFIED"),
            "sub_category": str(row.get("sub_category") or "UNCLASSIFIED"),
            "asset_class": str(row.get("asset_class") or "UNCLASSIFIED"),
        })
    total = sum((row["market_value_inr"] for row in normalized), ZERO)
    if total <= ZERO:
        raise ValueError("total portfolio market value must be positive")

    def group(field: str) -> list[dict[str, Any]]:
        totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for row in normalized:
            totals[row[field]] += row["market_value_inr"]
        return [
            {"name": name, "market_value_inr": _money(amount), "portfolio_weight_pct": _pct(amount, total)}
            for name, amount in sorted(totals.items(), key=lambda item: (-item[1], item[0].casefold()))
        ]

    ordered = sorted(normalized, key=lambda row: (-row["market_value_inr"], row["scheme_code"]))
    segment_totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    subcategory_totals: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
    for row in normalized:
        segment_totals[row["category_group"]] += row["market_value_inr"]
        subcategory_totals[(row["category_group"], row["sub_category"])] += row["market_value_inr"]
    return {
        "methodology_version": METHODOLOGY_VERSION,
        "portfolio_market_value_inr": _money(total),
        "scheme_count": len(normalized),
        "schemes": [{
            "scheme_code": row["scheme_code"],
            "scheme_name": row["scheme_name"],
            "amc": row["amc"],
            "category_group": row["category_group"],
            "sub_category": row["sub_category"],
            "asset_class": row["asset_class"],
            "market_value_inr": _money(row["market_value_inr"]),
            "portfolio_weight_pct": _pct(row["market_value_inr"], total),
            "segment_weight_pct": _pct(row["market_value_inr"], segment_totals[row["category_group"]]),
            "subcategory_weight_within_segment_pct": _pct(
                subcategory_totals[(row["category_group"], row["sub_category"])],
                segment_totals[row["category_group"]],
            ),
        } for row in ordered],
        "by_category": group("category_group"),
        "by_sub_category": group("sub_category"),
        "by_asset_class": group("asset_class"),
        "by_amc": group("amc"),
        "data_quality": {
            "classification_basis": "EXPLICIT_SCHEME_METADATA_ONLY",
            "unclassified_scheme_count": sum(1 for row in normalized if row["category_group"] == "UNCLASSIFIED" or row["asset_class"] == "UNCLASSIFIED"),
        },
    }


def allocation_drift(
    targets: Iterable[Mapping[str, Any]],
    *,
    portfolio_value_inr: Any,
) -> dict[str, Any]:
    """Compare actual values with a complete, mutually exclusive target set."""
    total = _d(portfolio_value_inr, "portfolio_value_inr")
    assert total is not None
    if total <= ZERO:
        raise ValueError("portfolio_value_inr must be positive")
    rows = list(targets)
    if not rows:
        raise ValueError("at least one target is required")
    seen: set[str] = set()
    preferred_total = ZERO
    normalized = []
    for row in rows:
        key = str(row.get("key") or "").strip()
        if not key or key in seen:
            raise ValueError("target keys must be present and unique")
        seen.add(key)
        minimum = _d(row.get("min_pct"), "min_pct")
        target = _d(row.get("target_pct"), "target_pct")
        maximum = _d(row.get("max_pct"), "max_pct")
        actual = _d(row.get("actual_value_inr"), "actual_value_inr")
        assert minimum is not None and target is not None and maximum is not None and actual is not None
        if minimum < ZERO or maximum > HUNDRED or minimum > target or target > maximum:
            raise ValueError(f"invalid target range for {key}")
        if actual < ZERO:
            raise ValueError(f"actual value cannot be negative for {key}")
        preferred_total += target
        normalized.append((key, minimum, target, maximum, actual))
    if abs(preferred_total - HUNDRED) > Decimal("0.01"):
        raise ValueError("preferred target percentages must reconcile to 100")
    actual_total = sum((item[4] for item in normalized), ZERO)
    if abs(actual_total - total) > Decimal("0.01"):
        raise ValueError("actual target values must reconcile to the complete portfolio value")

    results = []
    for key, minimum, target, maximum, actual in normalized:
        actual_pct = actual / total * HUNDRED
        drift = actual_pct - target
        target_value = total * target / HUNDRED
        gap = target_value - actual
        status = (
            "UNDERWEIGHT" if actual_pct < minimum
            else "OVERWEIGHT" if actual_pct > maximum
            else "WITHIN_BAND" if minimum <= actual_pct <= maximum
            else "WATCH"
        )
        results.append({
            "key": key,
            "actual_value_inr": _money(actual),
            "actual_weight_pct": str(actual_pct.quantize(FOUR_DP, rounding=ROUND_HALF_UP)),
            "min_pct": str(minimum),
            "target_pct": str(target),
            "max_pct": str(maximum),
            "drift_percentage_points": str(drift.quantize(FOUR_DP, rounding=ROUND_HALF_UP)),
            "amount_to_preferred_target_inr": _money(gap),
            "status": status,
        })
    return {
        "methodology_version": METHODOLOGY_VERSION,
        "portfolio_value_inr": _money(total),
        "target_count": len(results),
        "targets": results,
        "status": "AVAILABLE",
        "limitation": "Target drift is meaningful only for a complete, mutually exclusive target set with matching actual-value coverage.",
    }


def contribution_plan_preview(
    targets: Iterable[Mapping[str, Any]],
    *,
    portfolio_value_inr: Any,
    contribution_inr: Any,
) -> dict[str, Any]:
    """Allocate a new contribution to target deficits; never proposes sells."""
    total = _d(portfolio_value_inr, "portfolio_value_inr")
    contribution = _d(contribution_inr, "contribution_inr")
    assert total is not None and contribution is not None
    if total <= ZERO:
        raise ValueError("portfolio_value_inr must be positive")
    if contribution <= ZERO or contribution > Decimal("1000000000000"):
        raise ValueError("contribution_inr must be positive and within the supported limit")
    rows = list(targets)
    # Reuse the same complete-target validation and pre-contribution drift.
    drift = allocation_drift(rows, portfolio_value_inr=total)
    target_rows = {row["key"]: row for row in drift["targets"]}
    current_values = {
        str(row["key"]): _d(row.get("actual_value_inr"), "actual_value_inr")
        for row in rows
    }
    post_total = total + contribution
    deficits: dict[str, Decimal] = {}
    for key, target_row in target_rows.items():
        target_weight = _d(target_row["target_pct"], "target_pct")
        current = current_values[key]
        assert target_weight is not None and current is not None
        # Contribution allocation is calculated against post-contribution target values.
        deficits[key] = max(post_total * target_weight / HUNDRED - current, ZERO)
    deficit_total = sum(deficits.values(), ZERO)
    allocation_budget = min(contribution, deficit_total)
    allocations = []
    allocated_total = ZERO
    for key in sorted(deficits):
        amount = allocation_budget * deficits[key] / deficit_total if deficit_total > ZERO else ZERO
        rounded_amount = amount.quantize(CENT, rounding=ROUND_HALF_UP)
        allocations.append({
            "key": key,
            "current_value_inr": _money(current_values[key] or ZERO),
            "target_value_after_contribution_inr": _money(post_total * _d(target_rows[key]["target_pct"], "target_pct") / HUNDRED),
            "contribution_allocation_inr": _money(rounded_amount),
            "reason": "TARGET_GAP" if rounded_amount > ZERO else "NO_TARGET_GAP",
        })
        allocated_total += rounded_amount
    # Reconcile displayed paise exactly to the contribution budget.
    budget_rounded = allocation_budget.quantize(CENT, rounding=ROUND_HALF_UP)
    residual = budget_rounded - allocated_total
    if residual != ZERO and allocations and deficit_total > ZERO:
        chosen = max(allocations, key=lambda row: (deficits[row["key"]], row["key"]))
        adjusted = _d(chosen["contribution_allocation_inr"], "allocation") + residual
        chosen["contribution_allocation_inr"] = _money(adjusted)
        allocated_total += residual
    after = []
    for item in allocations:
        value = current_values[item["key"]] + _d(item["contribution_allocation_inr"], "allocation")
        after.append({
            "key": item["key"],
            "post_contribution_value_inr": _money(value),
            "post_contribution_weight_pct": _pct(value, post_total),
        })
    return {
        "methodology_version": METHODOLOGY_VERSION,
        "plan_type": "CONTRIBUTION_ONLY_PREVIEW",
        "portfolio_value_before_inr": _money(total),
        "proposed_contribution_inr": _money(contribution),
        "portfolio_value_after_inr": _money(post_total),
        "allocated_contribution_inr": _money(allocated_total),
        "unallocated_contribution_inr": _money(contribution - allocated_total),
        "allocations": allocations,
        "post_contribution_allocation": after,
        "status": "AVAILABLE" if deficit_total > ZERO else "NO_TARGET_GAP",
        "limitations": [
            "This is a target-gap allocation preview, not a buy instruction or transaction.",
            "It does not yet apply AMC, scheme, sector, liquidity, risk-budget or market-regime caps.",
            "Targets must be configured from a complete, mutually exclusive allocation dimension.",
        ],
    }


def parse_market_cap_classification_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse an operator-supplied, source-dated ISIN market-cap classification CSV."""
    from datetime import date

    if not isinstance(csv_text, str) or not csv_text.strip():
        raise ValueError("market-cap classification CSV is empty")
    if len(csv_text.encode("utf-8")) > 5_000_000:
        raise ValueError("market-cap classification CSV exceeds the 5 MB safety limit")
    reader = csv.DictReader(StringIO(csv_text.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise ValueError("market-cap classification CSV header is missing")

    def key(value: str) -> str:
        return "".join(ch.lower() for ch in value.strip().lstrip("\ufeff") if ch.isalnum())

    headers = {key(name): name for name in reader.fieldnames if name}
    if len(headers) != len([name for name in reader.fieldnames if name]):
        raise ValueError("market-cap classification CSV has duplicate or ambiguous headers")
    def pick(*names: str) -> str | None:
        return next((headers[name] for name in names if name in headers), None)

    isin_col = pick("isin", "isincode", "securityid")
    bucket_col = pick("marketcapbucket", "marketcap", "classification")
    from_col = pick("effectivefrom", "effectivefromdate")
    to_col = pick("effectiveto", "effectivetodate")
    source_date_col = pick("sourceasofdate", "classificationasofdate", "asofdate")
    if not all((isin_col, bucket_col, from_col, source_date_col)):
        raise ValueError("CSV requires ISIN, market-cap bucket, effective-from and source-as-of date columns")
    rows = []
    seen = set()
    for line_number, row in enumerate(reader, start=2):
        if not row or not any((value or "").strip() for value in row.values()):
            continue
        if None in row:
            raise ValueError(f"row {line_number}: more values than the CSV header defines")
        isin = (row.get(isin_col) or "").strip().upper()
        if not ISIN_PATTERN.fullmatch(isin):
            raise ValueError(f"row {line_number}: invalid ISIN")
        bucket_raw = (row.get(bucket_col) or "").strip().upper().replace(" ", "_").replace("-", "_")
        aliases = {"LARGE": "LARGE_CAP", "MID": "MID_CAP", "SMALL": "SMALL_CAP"}
        bucket = aliases.get(bucket_raw, bucket_raw)
        if bucket not in {"LARGE_CAP", "MID_CAP", "SMALL_CAP", "OTHER"}:
            raise ValueError(f"row {line_number}: unsupported market-cap bucket")
        try:
            effective_from = date.fromisoformat((row.get(from_col) or "").strip())
            effective_to_raw = (row.get(to_col) or "").strip() if to_col else ""
            effective_to = date.fromisoformat(effective_to_raw) if effective_to_raw else None
            source_as_of = date.fromisoformat((row.get(source_date_col) or "").strip())
        except ValueError as exc:
            raise ValueError(f"row {line_number}: dates must use YYYY-MM-DD") from exc
        if effective_to and effective_to < effective_from:
            raise ValueError(f"row {line_number}: effective-to precedes effective-from")
        identity = (isin, effective_from)
        if identity in seen:
            raise ValueError(f"row {line_number}: duplicate ISIN and effective-from mapping")
        seen.add(identity)
        rows.append({
            "security_id": isin,
            "market_cap_bucket": bucket,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "source_as_of_date": source_as_of,
        })
        if len(rows) > 20000:
            raise ValueError("market-cap classification CSV exceeds the 20,000-row safety limit")
    if not rows:
        raise ValueError("market-cap classification CSV contains no valid rows")
    return rows


def market_cap_allocation(
    securities: Iterable[Mapping[str, Any]],
    classifications: Iterable[Mapping[str, Any]],
    *,
    as_of_date: Any,
    portfolio_value_inr: Any,
    max_classification_age_days: int = 180,
) -> dict[str, Any]:
    """Classify look-through exposure only from verified, effective-dated ISIN mappings.

    A classification is eligible when its effective date covers the requested
    as-of date and its source as-of date is within the configured age. Missing,
    stale, non-ISIN and conflicting mappings remain explicit unclassified
    buckets. No company market cap is inferred from a security or fund name.
    """
    from datetime import date, datetime

    def as_date(value: Any, field: str):
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        try:
            return date.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be an ISO date") from exc

    as_of = as_date(as_of_date, "as_of_date")
    portfolio_value = _d(portfolio_value_inr, "portfolio_value_inr")
    assert portfolio_value is not None
    if portfolio_value <= ZERO:
        raise ValueError("portfolio_value_inr must be positive")
    if not isinstance(max_classification_age_days, int) or not 0 <= max_classification_age_days <= 3650:
        raise ValueError("max_classification_age_days must be between 0 and 3650")

    allowed = {"LARGE_CAP", "MID_CAP", "SMALL_CAP", "OTHER"}
    by_isin: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in classifications:
        if str(row.get("verification_status", "")).upper() != "VERIFIED":
            continue
        isin = str(row.get("security_id") or "").strip().upper()
        if not isin or not bool(row.get("is_isin", True)):
            continue
        bucket = str(row.get("market_cap_bucket") or "").upper()
        if bucket not in allowed:
            raise ValueError(f"unsupported market-cap bucket: {bucket}")
        effective_from = as_date(row.get("effective_from"), "effective_from")
        effective_to = as_date(row["effective_to"], "effective_to") if row.get("effective_to") else None
        source_as_of = as_date(row.get("source_as_of_date"), "source_as_of_date")
        source_hash = str(row.get("source_sha256") or "").lower()
        if len(source_hash) != 64 or any(ch not in "0123456789abcdef" for ch in source_hash):
            raise ValueError("verified classification requires a valid SHA-256 source hash")
        if not str(row.get("source_url") or "").strip():
            raise ValueError("verified classification requires a source URL")
        if effective_to and effective_to < effective_from:
            raise ValueError("classification effective_to cannot precede effective_from")
        by_isin[isin].append({
            "bucket": bucket,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "source_as_of_date": source_as_of,
            "source_url": str(row["source_url"]),
            "source_sha256": source_hash,
        })

    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    total_positive = ZERO
    classified = ZERO
    source_rows = []
    for security in securities:
        value = _d(security.get("lookthrough_value"), "lookthrough_value")
        assert value is not None
        if value <= ZERO:
            continue
        total_positive += value
        isin = str(security.get("security_id") or "").strip().upper()
        if not bool(security.get("is_isin")) or not isin:
            totals["UNCLASSIFIED_NON_ISIN"] += value
            continue
        candidates = [
            item for item in by_isin.get(isin, [])
            if item["effective_from"] <= as_of
            and (item["effective_to"] is None or item["effective_to"] >= as_of)
        ]
        if not candidates:
            totals["UNCLASSIFIED_NO_EFFECTIVE_MAPPING"] += value
            continue
        latest_start = max(item["effective_from"] for item in candidates)
        latest = [item for item in candidates if item["effective_from"] == latest_start]
        distinct = {(item["bucket"], item["source_sha256"]) for item in latest}
        if len(distinct) > 1:
            raise ValueError(f"conflicting verified classifications for {isin} on {as_of.isoformat()}")
        chosen = latest[0]
        age = (as_of - chosen["source_as_of_date"]).days
        if age < 0 or age > max_classification_age_days:
            totals["UNCLASSIFIED_STALE_MAPPING"] += value
            continue
        totals[chosen["bucket"]] += value
        classified += value
        source_rows.append({
            "security_id": isin,
            "market_cap_bucket": chosen["bucket"],
            "source_as_of_date": chosen["source_as_of_date"].isoformat(),
            "classification_age_days": age,
            "source_url": chosen["source_url"],
            "source_sha256": chosen["source_sha256"],
        })

    ordered = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    source_summary: dict[str, dict[str, Any]] = {}
    for source in source_rows:
        source_hash = source["source_sha256"]
        entry = source_summary.setdefault(source_hash, {
            "source_url": source["source_url"],
            "source_sha256": source_hash,
            "source_as_of_date": source["source_as_of_date"],
            "classified_security_count": 0,
        })
        entry["classified_security_count"] += 1
    return {
        "methodology_version": METHODOLOGY_VERSION,
        "as_of_date": as_of.isoformat(),
        "basis": "VERIFIED_EFFECTIVE_DATED_ISIN_CLASSIFICATIONS",
        "portfolio_value_inr": _money(portfolio_value),
        "positive_lookthrough_exposure_inr": _money(total_positive),
        "classified_exposure_inr": _money(classified),
        "classified_coverage_of_positive_lookthrough_pct": _pct(classified, total_positive),
        "classified_distribution": [
            {"market_cap_bucket": bucket, "exposure_inr": _money(value), "weight_of_total_portfolio_pct": _pct(value, portfolio_value), "weight_of_positive_lookthrough_pct": _pct(value, total_positive)}
            for bucket, value in ordered if bucket in allowed
        ],
        "unclassified_exposure": [
            {"reason": bucket, "exposure_inr": _money(value), "weight_of_total_portfolio_pct": _pct(value, portfolio_value), "weight_of_positive_lookthrough_pct": _pct(value, total_positive)}
            for bucket, value in ordered if bucket not in allowed
        ],
        "sources": sorted(source_summary.values(), key=lambda item: item["source_sha256"]),
        "limitations": [
            "Only verified, effective-dated ISIN classifications are used.",
            "Non-ISIN, missing and stale classifications remain unclassified; no partial subset is silently normalised to the full portfolio.",
            "Market-cap classifications are only as reliable and current as their cited source artifacts.",
        ],
    }


def amc_concentration(schemes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Calculate AMC concentration from scheme market values, not scheme counts."""
    allocation = portfolio_allocation(schemes)
    rows = allocation["by_amc"]
    amounts = [_d(row["market_value_inr"], "AMC market value") for row in rows]
    assert all(value is not None for value in amounts)
    values = [value for value in amounts if value is not None]
    hhi, effective = _hhi(values)
    total = _d(allocation["portfolio_market_value_inr"], "portfolio market value")
    assert total is not None
    top = lambda n: _pct(sum(values[:n], ZERO), total)
    return {
        "methodology_version": METHODOLOGY_VERSION,
        "basis": "CURRENT_SCHEME_MARKET_VALUE_BY_AMC",
        "portfolio_market_value_inr": _money(total),
        "amc_count": len(rows),
        "amcs": [{
            **row,
            "rank": index + 1,
        } for index, row in enumerate(rows)],
        "top_1_amc_weight_pct": top(1),
        "top_3_amc_weight_pct": top(3),
        "top_5_amc_weight_pct": top(5),
        "hhi_points": hhi,
        "effective_amc_count": effective,
        "interpretation": "AMC concentration is based on the market value of schemes held. It is not underlying-company concentration.",
    }


def holdings_disclosure_coverage(holdings: Iterable[Mapping[str, Any]]) -> str | None:
    """Return positive ISIN-identified weight as a share of all positive disclosed weight.

    The denominator includes positive ISIN and non-ISIN rows. Negative rows do not
    inflate coverage. None means the disclosure has no positive reported exposure.
    """
    total_positive = ZERO
    positive_isin = ZERO
    for row in holdings:
        weight = _d(row.get("weight_pct"), "holding weight")
        assert weight is not None
        if weight <= ZERO:
            continue
        total_positive += weight
        if bool(row.get("is_isin")):
            positive_isin += weight
    return _pct(positive_isin, total_positive)


def holdings_overlap_matrix(
    funds: Iterable[Mapping[str, Any]],
    *,
    disclosure_coverage_threshold_pct: Any = 0,
) -> dict[str, Any]:
    """Build pairwise overlap and portfolio-wide duplicated exposure.

    Each fund requires scheme_code, portfolio_value_inr, and holdings. Each
    holding requires security_id, is_isin, weight_pct. Only positive ISIN
    positions are cross-matched. Portfolio-wide duplication is the sum, per
    security, of all fund contributions except the largest single-fund
    contribution. This counts duplicated exposure once, not once per pair.

    Disclosure coverage is supplied separately as a percentage of fund NAV;
    a missing coverage value remains unknown and can withhold pair metrics.
    """
    threshold = _d(disclosure_coverage_threshold_pct, "disclosure_coverage_threshold_pct")
    assert threshold is not None
    if threshold < ZERO or threshold > HUNDRED:
        raise ValueError("disclosure coverage threshold must be between 0 and 100")
    fund_rows = list(funds)
    if len(fund_rows) > 200:
        raise ValueError("overlap matrix is limited to 200 active funds per calculation")
    normalized: list[dict[str, Any]] = []
    codes: set[str] = set()
    security_contributions: dict[str, list[tuple[str, Decimal]]] = defaultdict(list)
    fund_exposures: dict[str, dict[str, Decimal]] = {}
    gross_positive = ZERO
    for fund in fund_rows:
        code = str(fund.get("scheme_code", "")).strip()
        if not code or code in codes:
            raise ValueError("scheme_code must be present and unique")
        codes.add(code)
        nav = _d(fund.get("portfolio_value_inr"), "portfolio_value_inr")
        assert nav is not None
        if nav < ZERO:
            raise ValueError("fund portfolio value cannot be negative")
        coverage = _d(fund.get("disclosure_coverage_pct"), "disclosure_coverage_pct", allow_none=True)
        if coverage is not None and (coverage < ZERO or coverage > HUNDRED):
            raise ValueError("disclosure coverage must be between 0 and 100")
        exposures: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for holding in fund.get("holdings") or []:
            if not bool(holding.get("is_isin")):
                continue
            security_id = str(holding.get("security_id") or "").strip().upper()
            if not security_id:
                continue
            weight = _d(holding.get("weight_pct"), "holding weight")
            assert weight is not None
            if weight <= ZERO:
                continue
            contribution = nav * weight / HUNDRED
            exposures[security_id] += contribution
        fund_exposures[code] = dict(exposures)
        gross_positive += sum(exposures.values(), ZERO)
        for security_id, amount in exposures.items():
            security_contributions[security_id].append((code, amount))
        normalized.append({
            "scheme_code": code,
            "scheme_name": str(fund.get("scheme_name") or code),
            "portfolio_value_inr": nav,
            "disclosure_coverage_pct": coverage,
            "disclosure_as_of_date": fund.get("disclosure_as_of_date"),
            "disclosure_age_days": fund.get("disclosure_age_days"),
        })

    normalized.sort(key=lambda row: row["scheme_code"])
    pairs: list[dict[str, Any]] = []
    for i, left in enumerate(normalized):
        for right in normalized[i + 1:]:
            left_cov, right_cov = left["disclosure_coverage_pct"], right["disclosure_coverage_pct"]
            shared = set(fund_exposures[left["scheme_code"]]) & set(fund_exposures[right["scheme_code"]])
            overlap_amount = sum((
                min(fund_exposures[left["scheme_code"]][sid], fund_exposures[right["scheme_code"]][sid])
                for sid in shared
            ), ZERO)
            matched_left = sum((fund_exposures[left["scheme_code"]][sid] for sid in shared), ZERO)
            matched_right = sum((fund_exposures[right["scheme_code"]][sid] for sid in shared), ZERO)
            below_threshold = (
                left_cov is not None and right_cov is not None
                and (left_cov < threshold or right_cov < threshold)
            )
            withheld = threshold > ZERO and (
                left_cov is None or right_cov is None or below_threshold
            )
            pair_status = (
                "WITHHELD_LOW_OR_UNKNOWN_COVERAGE" if withheld
                else "PARTIAL_COVERAGE_UNKNOWN" if left_cov is None or right_cov is None
                else "PARTIAL_BELOW_CONFIGURED_THRESHOLD" if below_threshold
                else "AVAILABLE"
            )
            pairs.append({
                "scheme_a": left["scheme_code"],
                "scheme_b": right["scheme_code"],
                "scheme_a_name": left["scheme_name"],
                "scheme_b_name": right["scheme_name"],
                "overlap_inr": None if withheld else _money(overlap_amount),
                "overlap_pct_of_scheme_a_nav": None if withheld else _pct(overlap_amount, left["portfolio_value_inr"]),
                "overlap_pct_of_scheme_b_nav": None if withheld else _pct(overlap_amount, right["portfolio_value_inr"]),
                "common_isin_count": len(shared),
                "matched_isin_exposure_a_inr": _money(matched_left),
                "matched_isin_exposure_b_inr": _money(matched_right),
                "disclosure_coverage_a_pct": str(left_cov) if left_cov is not None else None,
                "disclosure_coverage_b_pct": str(right_cov) if right_cov is not None else None,
                "disclosure_as_of_a": left["disclosure_as_of_date"],
                "disclosure_as_of_b": right["disclosure_as_of_date"],
                "disclosure_age_days_a": left["disclosure_age_days"],
                "disclosure_age_days_b": right["disclosure_age_days"],
                "status": pair_status,
            })

    duplicated = ZERO
    duplicated_securities = []
    for security_id, contributions in security_contributions.items():
        total = sum((amount for _, amount in contributions), ZERO)
        largest = max((amount for _, amount in contributions), default=ZERO)
        duplicate = max(total - largest, ZERO)
        if duplicate > ZERO:
            duplicated += duplicate
            duplicated_securities.append({
                "security_id": security_id,
                "fund_count": len(contributions),
                "gross_exposure_inr": _money(total),
                "duplicated_exposure_inr": _money(duplicate),
            })
    duplicated_securities.sort(key=lambda row: Decimal(row["duplicated_exposure_inr"]), reverse=True)
    return {
        "methodology_version": METHODOLOGY_VERSION,
        "basis": "POSITIVE_ISIN_HOLDINGS_FROM_SUPPLIED_DISCLOSURES",
        "fund_count": len(normalized),
        "pair_count": len(pairs),
        "pairs": pairs,
        "portfolio_duplication": {
            "method": "SUM_PER_SECURITY_OF_TOTAL_FUND_EXPOSURE_MINUS_LARGEST_SINGLE_FUND_EXPOSURE",
            "duplicated_exposure_inr": _money(duplicated),
            "gross_positive_lookthrough_exposure_inr": _money(gross_positive),
            "duplicated_share_of_gross_positive_lookthrough_pct": _pct(duplicated, gross_positive),
            "duplicated_security_count": len(duplicated_securities),
            "top_duplicated_securities": duplicated_securities[:10],
            "limitation": "Only positive ISIN-matched holdings are included. Non-ISIN, missing, stale or unverified disclosures are excluded and must be shown separately by the caller.",
        },
    }
