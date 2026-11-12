"""Verified NAV unit-scale adjustments and conservative discontinuity quality gates.

Raw AMFI observations are never modified. Adjustments are applied only to the
analytics series and are versioned in every research snapshot for auditability.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

NAV_ADJUSTMENT_REGISTRY_VERSION = "2026-11-12.2"

# ICICI Prudential Overnight Fund changed unit face value from Rs.100 to
# Rs.1,000 effective 16-Aug-2022. The AMC notice states that existing unit
# holdings were adjusted proportionately without changing holding value. Its
# factsheet records the corresponding pre/post NAV levels. The event applies
# across the fund's 20 AMFI plan/option codes listed below.
_ICICI_OVERNIGHT_SCHEME_CODES = (
    *range(145535, 145551),
    *range(149408, 149412),
)

_VERIFIED_EVENTS: tuple[dict[str, Any], ...] = (
    {
        "scheme_codes": frozenset(_ICICI_OVERNIGHT_SCHEME_CODES),
        "effective_date": date(2022, 8, 16),
        "factor": 10.0,
        "action": "unit_consolidation",
        "source_urls": (
            "https://fundsindia.com/blog/wp-content/uploads/2022/08/Attachment74998attachmentsChange-in-FV-Overnight-Fund.pdf",
            "https://www.icicipruamc.com/blob/sebi-repo/Advertisements/2026/February/Filing%20date%2010-02-2026/Release%20date%2006-02-2026/Advertisements/Annexure%203-%20Big%20Factsheet.pdf",
            "https://stockexact.com/mutual-funds/icici-prudential-overnight-fund-direct-growth/nav-history",
        ),
        "source_note": (
            "ICICI Prudential AMC's notice changes unit face value from "
            "Rs.100 to Rs.1,000 effective 16-Aug-2022 and states that existing "
            "unit holdings are adjusted proportionately without changing "
            "holding value. The AMC factsheet records the corresponding "
            "pre/post NAV levels; independent NAV history identifies the "
            "17-Aug-2022 level reset. Pre-event NAVs are expressed in "
            "post-change units by multiplying by 10."
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
    window_points: Iterable[tuple[date, float]] = (),
) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    """Suppress only period/window metrics crossed by an unverified NAV jump."""
    periods = dict(metrics.get("period_returns") or {})
    affected_periods: dict[str, list[dict[str, Any]]] = {}
    for label, days in _PERIOD_DAYS.items():
        target_date = latest_date - timedelta(days=days)
        max_baseline_gap_days = 35 if label in {"3Y", "5Y"} else 7
        baseline_floor = target_date - timedelta(days=max_baseline_gap_days)
        events = [
            event for event in discontinuities
            if event["nav_date"] > baseline_floor
        ]
        if events:
            periods[label] = None
            affected_periods[label] = events

    window_start = latest_date - timedelta(days=window_days)
    window_events = [
        event for event in discontinuities if event["nav_date"] >= window_start
    ]
    window_rows = list(window_points)
    gap_days = [
        (current_date - previous_date).days
        for (previous_date, _), (current_date, _) in zip(window_rows, window_rows[1:])
    ]
    long_gaps = [gap for gap in gap_days if gap > 7]
    mixed_frequency_risk = bool(long_gaps)

    if window_events:
        for key in (
            "total_return",
            "cagr",
            "annualized_volatility",
            "volatility",
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
            for item in (metrics.get("monthly_returns") or [])
            if item.get("month") not in event_months
        ]
        metrics["risk_statistics_status"] = "REVIEW_REQUIRED"

    if mixed_frequency_risk:
        for key in (
            "annualized_volatility",
            "volatility",
            "sharpe_ratio",
            "sortino_ratio",
            "max_drawdown",
        ):
            metrics[key] = None
        if not window_events:
            metrics["risk_statistics_status"] = "MIXED_FREQUENCY_NOT_COMPARABLE"

    if not window_events and not mixed_frequency_risk:
        metrics["risk_statistics_status"] = (
            "OK" if metrics.get("annualized_volatility") is not None
            else "INSUFFICIENT_DAILY_OBSERVATIONS"
        )

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

    if mixed_frequency_risk:
        quality_flags.append(
            {
                "type": "mixed_frequency_risk_series",
                "max_observation_gap_days": max(long_gaps),
                "gaps_over_seven_days": len(long_gaps),
                "affected_periods": [],
                "affects_window_metrics": True,
            }
        )

    return metrics, "REVIEW_REQUIRED" if quality_flags else "PASS", quality_flags
