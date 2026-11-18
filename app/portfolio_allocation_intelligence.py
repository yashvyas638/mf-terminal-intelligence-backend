"""Portfolio-level allocation, AMC concentration and holdings-overlap calculations.

Pure Decimal-based calculations. Inputs must come from current, owner-scoped
portfolio valuations and VERIFIED dated fund disclosures. This module does not
fetch data, infer classifications, or turn missing inputs into zero coverage.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Mapping

METHODOLOGY_VERSION = "portfolio-allocation-v1.0.0"
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
        "sources": source_rows,
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
    normalized: list[dict[str, Any]] = []
    codes: set[str] = set()
    security_contributions: dict[str, list[tuple[str, Decimal]]] = defaultdict(list)
    fund_exposures: dict[str, dict[str, Decimal]] = {}
    gross_positive = ZERO
    for fund in funds:
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
