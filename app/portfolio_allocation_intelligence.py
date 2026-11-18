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
