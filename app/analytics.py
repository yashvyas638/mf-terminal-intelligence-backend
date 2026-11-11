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
        "max_drawdown": max_drawdown(values), "sharpe_ratio": sharpe, "sortino_ratio": sortino,
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
