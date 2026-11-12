"""Concentration and identity-coverage metrics for disclosed fund look-through.

Metrics describe only observed verified disclosure rows. They are not a
substitute for complete underlying security holdings or live security prices.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


def _decimal(value: Any, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal value") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be a finite decimal value")
    return parsed


def security_concentration_metrics(
    securities: Iterable[dict[str, Any]],
    *,
    portfolio_value: Any,
    valuation_complete: bool,
) -> dict[str, Any]:
    """Calculate HHI, effective names and top-N weights on positive disclosed exposure.

    Negative rows (e.g. derivative liabilities) are disclosed separately and
    excluded from HHI. HHI is calculated on the positive observed exposure
    denominator, never silently on total portfolio value when coverage is partial.
    """
    total_portfolio = _decimal(portfolio_value, "portfolio_value")
    if total_portfolio < 0:
        raise ValueError("portfolio_value cannot be negative")

    positive: list[tuple[Decimal, bool]] = []
    negative_total = Decimal("0")
    for item in securities:
        exposure = _decimal(item.get("lookthrough_value", 0), "lookthrough_value")
        is_isin = bool(item.get("is_isin"))
        if exposure > 0:
            positive.append((exposure, is_isin))
        elif exposure < 0:
            negative_total += exposure

    positive.sort(key=lambda item: item[0], reverse=True)
    positive_total = sum((value for value, _ in positive), Decimal("0"))
    isin_positive = sum((value for value, is_isin in positive if is_isin), Decimal("0"))
    shares = [value / positive_total for value, _ in positive] if positive_total > 0 else []
    hhi_fraction = sum((share * share for share in shares), Decimal("0"))
    effective_count = (Decimal("1") / hhi_fraction) if hhi_fraction > 0 else None

    def top_weight(count: int) -> str | None:
        if positive_total <= 0:
            return None
        amount = sum((value for value, _ in positive[:count]), Decimal("0"))
        return str((amount / positive_total * Decimal("100")).quantize(Decimal("0.0001")))

    return {
        "basis": "OBSERVED_VERIFIED_DISCLOSURES_ONLY",
        "positive_disclosed_exposure_inr": str(positive_total.quantize(Decimal("0.01"))),
        "negative_disclosed_exposure_inr": str(negative_total.quantize(Decimal("0.01"))),
        "positive_security_count": len(positive),
        "isin_security_count": sum(1 for _, is_isin in positive if is_isin),
        "non_isin_security_count": sum(1 for _, is_isin in positive if not is_isin),
        "isin_identity_coverage_pct": (
            str((isin_positive / positive_total * Decimal("100")).quantize(Decimal("0.0001")))
            if positive_total > 0 else None
        ),
        "top_1_weight_of_observed_positive_pct": top_weight(1),
        "top_5_weight_of_observed_positive_pct": top_weight(5),
        "top_10_weight_of_observed_positive_pct": top_weight(10),
        "hhi_points": (
            str((hhi_fraction * Decimal("10000")).quantize(Decimal("0.01")))
            if positive_total > 0 else None
        ),
        "effective_security_count": (
            str(effective_count.quantize(Decimal("0.0001")))
            if effective_count is not None else None
        ),
        "observed_positive_exposure_as_pct_of_portfolio": (
            str((positive_total / total_portfolio * Decimal("100")).quantize(Decimal("0.0001")))
            if valuation_complete and total_portfolio > 0 else None
        ),
        "portfolio_value_denominator_available": bool(valuation_complete and total_portfolio > 0),
        "interpretation": (
            "Concentration is normalized to positive exposure in verified disclosures only. "
            "Missing scheme disclosures and non-ISIN identity gaps can hide additional concentration. "
            "Negative exposures are reported separately and excluded from HHI."
        ),
    }
