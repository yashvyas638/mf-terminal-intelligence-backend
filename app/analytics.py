"""Auditable mutual-fund performance and risk calculations.

Metrics are calculated from dated NAV observations. They are estimates from available
observations, not guarantees; annualisation assumes 252 trading observations/year.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Iterable


def _clean_series(points: Iterable[tuple[date, float]]) -> list[tuple[date, float]]:
    rows = sorted((d, float(v)) for d, v in points if v is not None and math.isfinite(float(v)) and float(v) > 0)
    dedup: dict[date, float] = {}
    for d, v in rows:
        dedup[d] = v
    return list(dedup.items())


def max_drawdown(values: list[float]) -> float | None:
    if not values:
        return None
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1.0)
    return worst


def drawdown_profile(points: Iterable[tuple[date, float]]) -> dict:
    """Describe the worst peak-to-trough loss and recovery using observed NAV dates.

    Durations are calendar days between actual observations. An unrecovered
    drawdown is reported as open; no interpolation or assumed recovery is used.
    """
    rows = _clean_series(points)
    if len(rows) < 2:
        return {"status": "INSUFFICIENT_DATA"}

    peak_date, peak_value = rows[0]
    worst = 0.0
    worst_peak_date = peak_date
    worst_trough_date = peak_date
    worst_recovery_date = None
    worst_recovery_days = None
    active_trough_date = None
    active_trough_value = peak_value
    longest_underwater_days = 0
    longest_underwater_peak = peak_date
    longest_underwater_recovery = None

    for current_date, current_value in rows[1:]:
        if current_value >= peak_value:
            if active_trough_date is not None:
                duration = (current_date - peak_date).days
                if duration > longest_underwater_days:
                    longest_underwater_days = duration
                    longest_underwater_peak = peak_date
                    longest_underwater_recovery = current_date
                active_trough_date = None
            peak_date, peak_value = current_date, current_value
            active_trough_value = current_value
            continue

        drawdown = current_value / peak_value - 1.0
        if active_trough_date is None:
            active_trough_date = current_date
            active_trough_value = current_value
        elif current_value < active_trough_value:
            active_trough_date = current_date
            active_trough_value = current_value

        if drawdown < worst:
            worst = drawdown
            worst_peak_date = peak_date
            worst_trough_date = current_date
            worst_recovery_date = None
            worst_recovery_days = None

    if active_trough_date is not None:
        duration = (rows[-1][0] - peak_date).days
        if duration > longest_underwater_days:
            longest_underwater_days = duration
            longest_underwater_peak = peak_date
            longest_underwater_recovery = None

    if worst < 0:
        for current_date, current_value in rows:
            if current_date > worst_trough_date and current_value >= next(
                value for observed_date, value in rows if observed_date == worst_peak_date
            ):
                worst_recovery_date = current_date
                worst_recovery_days = (current_date - worst_peak_date).days
                break

    latest_date, latest_value = rows[-1]
    latest_peak = max(value for _, value in rows)
    return {
        "status": "OK",
        "max_drawdown": worst,
        "worst_peak_date": worst_peak_date.isoformat(),
        "worst_trough_date": worst_trough_date.isoformat(),
        "worst_recovery_date": worst_recovery_date.isoformat() if worst_recovery_date else None,
        "worst_recovery_days": worst_recovery_days,
        "longest_underwater_days": longest_underwater_days,
        "longest_underwater_peak_date": longest_underwater_peak.isoformat(),
        "longest_underwater_recovery_date": longest_underwater_recovery.isoformat() if longest_underwater_recovery else None,
        "current_drawdown": latest_value / latest_peak - 1.0,
        "as_of_date": latest_date.isoformat(),
        "methodology": "Calendar-day durations between observed NAV dates; recovery requires NAV to regain the prior peak.",
    }


def performance_metrics(points: Iterable[tuple[date, float]], risk_free_rate: float = 0.06) -> dict:
    rows = _clean_series(points)
    if len(rows) < 2:
        return {"observations": len(rows), "status": "INSUFFICIENT_DATA"}
    dates = [r[0] for r in rows]
    values = [r[1] for r in rows]
    daily = [values[i] / values[i - 1] - 1 for i in range(1, len(values))]
    span_days = max((dates[-1] - dates[0]).days, 1)
    years = span_days / 365.25
    total_return = values[-1] / values[0] - 1
    cagr = (values[-1] / values[0]) ** (1 / years) - 1 if years > 0 else None
    mean = sum(daily) / len(daily)
    variance = sum((r - mean) ** 2 for r in daily) / (len(daily) - 1) if len(daily) > 1 else 0.0
    volatility = math.sqrt(variance) * math.sqrt(252)
    rf_daily = (1 + risk_free_rate) ** (1 / 252) - 1
    excess = [r - rf_daily for r in daily]
    downside = [min(r - rf_daily, 0.0) for r in daily]
    downside_dev = math.sqrt(sum(x * x for x in downside) / len(downside)) * math.sqrt(252)
    sharpe = ((sum(excess) / len(excess)) * 252 / volatility) if volatility > 0 else None
    sortino = ((sum(excess) / len(excess)) * 252 / downside_dev) if downside_dev > 0 else None
    periods = {}
    for label, days in (("1M", 30), ("3M", 90), ("6M", 182), ("1Y", 365), ("3Y", 365 * 3), ("5Y", 365 * 5)):
        target = dates[-1].toordinal() - days
        eligible = [(d, v) for d, v in rows if d.toordinal() <= target]
        periods[label] = (values[-1] / eligible[-1][1] - 1) if eligible else None
    monthly: dict[str, tuple[date, float]] = {}
    for d, v in rows:
        key = d.strftime("%Y-%m")
        monthly[key] = (d, v)
    month_rows = list(monthly.items())
    monthly_returns = []
    for i in range(1, len(month_rows)):
        monthly_returns.append({"month": month_rows[i][0], "return": month_rows[i][1][1] / month_rows[i-1][1][1] - 1})
    return {
        "status": "OK", "observations": len(rows), "start_date": dates[0].isoformat(),
        "end_date": dates[-1].isoformat(), "span_days": span_days,
        "start_nav": values[0], "latest_nav": values[-1],
        "total_return": total_return, "cagr": cagr, "annualized_volatility": volatility,
        "max_drawdown": max_drawdown(values), "drawdown_profile": drawdown_profile(rows), "sharpe_ratio": sharpe, "sortino_ratio": sortino,
        "risk_free_rate_assumption": risk_free_rate, "period_returns": periods,
        "monthly_returns": monthly_returns,
    }


def xirr(cashflows: list[tuple[date, float]]) -> float | None:
    """Annualized money-weighted return using a bracketed bisection solver."""
    flows = sorted(cashflows, key=lambda x: x[0])
    if len(flows) < 2 or not any(v < 0 for _, v in flows) or not any(v > 0 for _, v in flows):
        return None
    start = flows[0][0]
    def npv(rate: float) -> float:
        return sum(amount / ((1 + rate) ** ((d - start).days / 365.25)) for d, amount in flows)
    lo, hi = -0.9999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if not math.isfinite(f_lo) or not math.isfinite(f_hi) or f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7:
            return mid
        if f_lo * f_mid <= 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def rolling_return_series(
    points: Iterable[tuple[date, float]],
    window_days: int = 365,
    max_base_gap_days: int = 7,
) -> dict:
    """Calculate rolling NAV returns using real observations only.

    Each endpoint uses the latest observation on/before the target start date,
    provided it is no more than max_base_gap_days earlier. No interpolation is
    performed. Monthly endpoint sampling reduces redundant daily windows.
    """
    rows = _clean_series(points)
    if window_days < 30 or max_base_gap_days < 0:
        raise ValueError("invalid rolling-return window configuration")
    if len(rows) < 2:
        return {
            "status": "INSUFFICIENT_DATA",
            "window_days": window_days,
            "observations": len(rows),
            "items": [],
            "positive_window_rate": None,
        }

    # Retain the last available observation in each calendar month, plus the
    # final observation, so the endpoint series is stable and easy to explain.
    monthly: dict[str, tuple[date, float]] = {}
    for point in rows:
        monthly[point[0].strftime("%Y-%m")] = point
    endpoints = list(monthly.values())
    if endpoints[-1] != rows[-1]:
        endpoints.append(rows[-1])

    results = []
    for end_date, end_value in endpoints:
        target_ordinal = end_date.toordinal() - window_days
        candidate_index = None
        for index, (start_date, _) in enumerate(rows):
            if start_date.toordinal() <= target_ordinal:
                candidate_index = index
            else:
                break
        if candidate_index is None:
            continue
        start_date, start_value = rows[candidate_index]
        gap_days = target_ordinal - start_date.toordinal()
        if gap_days > max_base_gap_days or start_value <= 0:
            continue
        elapsed_days = (end_date - start_date).days
        if elapsed_days <= 0:
            continue
        total_return = end_value / start_value - 1.0
        annualized = (end_value / start_value) ** (365.25 / elapsed_days) - 1.0
        results.append({
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "base_date_gap_days": gap_days,
            "total_return": total_return,
            "annualized_return": annualized,
        })
    positive = sum(item["total_return"] > 0 for item in results)
    return {
        "status": "OK" if results else "INSUFFICIENT_DATA",
        "window_days": window_days,
        "observations": len(results),
        "positive_windows": positive,
        "negative_or_zero_windows": len(results) - positive,
        "positive_window_rate": positive / len(results) if results else None,
        "items": results,
        "methodology": (
            "Monthly endpoint samples; each start uses the latest actual NAV on or before "
            "the target date, only when the base-date gap is at most "
            f"{max_base_gap_days} days. No interpolation."
        ),
    }


def research_metrics(
    points: Iterable[tuple[date, float]],
    risk_free_rate: float = 0.06,
) -> dict:
    """Combine the existing NAV performance metrics with rolling diagnostics."""
    rows = _clean_series(points)
    base = performance_metrics(rows, risk_free_rate=risk_free_rate)
    if base.get("status") != "OK":
        return {
            **base,
            "rolling_1y": rolling_return_series(rows, 365),
            "rolling_3y": rolling_return_series(rows, 365 * 3),
        }
    rolling_1y = rolling_return_series(rows, 365)
    rolling_3y = rolling_return_series(rows, 365 * 3)
    monthly_returns = base.get("monthly_returns", [])
    positive_months = sum(item["return"] > 0 for item in monthly_returns)
    base.update({
        "downside_deviation": (
            math.sqrt(
                sum(min(item["return"] - ((1 + risk_free_rate) ** (1 / 12) - 1), 0.0) ** 2
                    for item in monthly_returns) / len(monthly_returns)
            ) * math.sqrt(12)
            if monthly_returns else None
        ),
        "positive_month_rate": positive_months / len(monthly_returns) if monthly_returns else None,
        "positive_months": positive_months,
        "negative_or_zero_months": len(monthly_returns) - positive_months,
        "rolling_1y": rolling_1y,
        "rolling_3y": rolling_3y,
        "consistency_note": (
            "Consistency is reported as the observed share of positive monthly NAV returns "
            "and positive rolling windows; it is not a proprietary quality score."
        ),
    })
    return base
