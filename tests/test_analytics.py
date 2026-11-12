from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.analytics import benchmark_comparison_metrics, fifo_capital_gains, max_drawdown, performance_metrics, portfolio_risk_metrics, project_financial_goal, rolling_return_series, research_metrics, xirr


def test_performance_metrics_are_finite_and_have_expected_return():
    start = date(2024, 1, 1)
    points = [(start + timedelta(days=i * 30), 100 + i * 10) for i in range(13)]
    result = performance_metrics(points)
    assert result["status"] == "OK"
    assert result["total_return"] == pytest.approx(1.2)
    assert result["observations"] == 13
    assert result["max_drawdown"] == 0


def test_max_drawdown():
    assert max_drawdown([100, 120, 90, 110]) == -0.25


def test_xirr_positive_for_profit():
    start = date(2024, 1, 1)
    result = xirr([(start, -1000), (start + timedelta(days=365), 1100)])
    assert result is not None
    assert 0.09 < result < 0.11


def test_xirr_rejects_one_sided_cashflows():
    assert xirr([(date(2024, 1, 1), -100), (date(2025, 1, 1), -100)]) is None


def test_rolling_returns_uses_real_monthly_endpoints():
    start = date(2022, 1, 1)
    points = [(start + timedelta(days=i), 100 + i * 0.05) for i in range(1500)]
    result = rolling_return_series(points, window_days=365)
    assert result["status"] == "OK"
    assert result["observations"] > 6
    assert result["positive_windows"] == result["observations"]
    assert result["positive_window_rate"] == 1.0
    assert all(item["base_date_gap_days"] <= 7 for item in result["items"])


def test_rolling_returns_skips_windows_without_nearby_actual_base_nav():
    points = [
        (date(2023, 1, 1), 100.0),
        (date(2024, 1, 20), 110.0),
        (date(2024, 2, 20), 112.0),
        (date(2024, 3, 20), 115.0),
    ]
    result = rolling_return_series(points, window_days=365, max_base_gap_days=7)
    assert result["observations"] == 0
    assert result["status"] == "INSUFFICIENT_DATA"


def test_research_metrics_exposes_consistency_as_observed_rate_not_score():
    start = date(2022, 1, 1)
    points = [(start + timedelta(days=i), 100 + i * 0.05) for i in range(1500)]
    result = research_metrics(points)
    assert result["status"] == "OK"
    assert result["positive_month_rate"] == 1.0
    assert "consistency_note" in result
    assert result["rolling_1y"]["status"] == "OK"


def test_drawdown_profile_reports_peak_trough_and_recovery_dates():
    from app.analytics import drawdown_profile

    points = [
        (date(2024, 1, 1), 100.0),
        (date(2024, 1, 10), 120.0),
        (date(2024, 1, 20), 90.0),
        (date(2024, 2, 1), 110.0),
        (date(2024, 2, 15), 120.0),
        (date(2024, 2, 20), 126.0),
    ]
    result = drawdown_profile(points)
    assert result["status"] == "OK"
    assert result["max_drawdown"] == pytest.approx(-0.25)
    assert result["worst_peak_date"] == "2024-01-10"
    assert result["worst_trough_date"] == "2024-01-20"
    assert result["worst_recovery_date"] == "2024-02-15"
    assert result["worst_recovery_days"] == 36
    assert result["current_drawdown"] == 0


def test_drawdown_profile_marks_unrecovered_drawdown_open():
    from app.analytics import drawdown_profile

    points = [
        (date(2024, 1, 1), 100.0),
        (date(2024, 1, 10), 120.0),
        (date(2024, 1, 20), 90.0),
        (date(2024, 2, 1), 105.0),
    ]
    result = drawdown_profile(points)
    assert result["max_drawdown"] == pytest.approx(-0.25)
    assert result["worst_recovery_date"] is None
    assert result["worst_recovery_days"] is None
    assert result["longest_underwater_days"] == 22
    assert result["current_drawdown"] == pytest.approx(-0.125)

def test_benchmark_comparison_uses_exact_common_dates_and_reports_risk_statistics():
    start = date(2025, 1, 1)
    fund_points = []
    benchmark_points = []
    fund_value = 100.0
    benchmark_value = 100.0
    for index in range(80):
        observed = start + timedelta(days=index)
        fund_value *= 1 + 0.001 + (index % 5) * 0.0002
        benchmark_value *= 1 + 0.0006 + (index % 7) * 0.00015
        fund_points.append((observed, fund_value))
        if index not in {11, 12, 13, 14, 15, 16, 17, 18}:
            benchmark_points.append((observed, benchmark_value))

    result = benchmark_comparison_metrics(fund_points, benchmark_points)
    assert result["status"] == "OK"
    assert result["common_observations"] == 72
    assert result["risk_return_observations"] == 70
    assert result["fund_total_return"] > result["benchmark_total_return"]
    assert result["risk_statistics_status"] == "OK"
    assert result["tracking_error"] is not None
    assert result["information_ratio"] is not None
    assert "No forward-fill or interpolation" in result["methodology"]


def test_benchmark_comparison_does_not_interpolate_or_fabricate_daily_risk_statistics():
    start = date(2025, 1, 1)
    fund_points = [(start + timedelta(days=index), 100 + index) for index in range(80)]
    benchmark_points = [(start + timedelta(days=index), 100 + index * 0.8) for index in range(0, 80, 10)]
    result = benchmark_comparison_metrics(fund_points, benchmark_points)
    assert result["common_observations"] == len(benchmark_points)
    assert result["risk_return_observations"] == 0
    assert result["risk_statistics_status"] == "INSUFFICIENT_DAILY_OBSERVATIONS"
    assert result["beta"] is None
    assert result["tracking_error"] is None


def test_benchmark_comparison_returns_insufficient_data_without_common_dates():
    result = benchmark_comparison_metrics(
        [(date(2025, 1, 1), 100.0), (date(2025, 1, 2), 101.0)],
        [(date(2025, 1, 3), 100.0), (date(2025, 1, 4), 101.0)],
    )
    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["common_observations"] == 0

def test_portfolio_risk_uses_current_value_weights_and_reports_empirical_tail_risk():
    start = date(2025, 1, 1)
    first = []
    second = []
    value_a = 100.0
    value_b = 100.0
    for index in range(100):
        observed = start + timedelta(days=index)
        return_a = (0.001 if index % 6 else -0.012)
        return_b = (0.0007 if index % 8 else -0.008)
        value_a *= 1 + return_a
        value_b *= 1 + return_b
        first.append((observed, value_a))
        second.append((observed, value_b))

    result = portfolio_risk_metrics([(0.7, first), (0.3, second)])
    assert result["status"] == "OK"
    assert result["common_observations"] == 100
    assert result["daily_return_observations"] == 99
    assert result["annualized_volatility"] > 0
    assert result["historical_var_95"] > 0
    assert result["historical_cvar_95"] >= result["historical_var_95"]
    assert result["worst_1d_return"] < 0
    assert result["worst_5d_return"] is not None
    assert result["worst_21d_return"] is not None
    assert result["max_drawdown"] < 0


def test_portfolio_risk_does_not_forward_fill_or_join_across_large_gaps():
    start = date(2025, 1, 1)
    first = [(start + timedelta(days=index), 100 + index * 0.2) for index in range(80)]
    second = [(start + timedelta(days=index), 100 + index * 0.1) for index in range(0, 80, 10)]
    result = portfolio_risk_metrics([(0.5, first), (0.5, second)])
    assert result["common_observations"] == 8
    assert result["daily_return_observations"] == 0
    assert result["status"] == "INSUFFICIENT_HISTORY"
    assert result["annualized_volatility"] is None


def test_portfolio_risk_returns_insufficient_history_for_short_series():
    start = date(2025, 1, 1)
    points = [(start + timedelta(days=index), 100 + index) for index in range(10)]
    result = portfolio_risk_metrics([(1.0, points)])
    assert result["status"] == "INSUFFICIENT_HISTORY"
    assert result["annualized_volatility"] is None

def test_fifo_capital_gains_matches_redemptions_to_acquisition_lots():
    transactions = [
        {
            "id": 1, "scheme_code": 120001, "transaction_type": "BUY",
            "transaction_date": date(2024, 1, 1), "units": "5",
            "amount": "500", "charges": "5",
        },
        {
            "id": 2, "scheme_code": 120001, "transaction_type": "BUY",
            "transaction_date": date(2025, 1, 1), "units": "5",
            "amount": "600", "charges": "5",
        },
        {
            "id": 3, "scheme_code": 120001, "transaction_type": "SELL",
            "transaction_date": date(2025, 6, 1), "units": "6",
            "amount": "720", "charges": "6",
        },
    ]
    result = fifo_capital_gains(
        transactions,
        {120001: Decimal("130")},
    )
    assert result["realized_lot_count"] == 2
    assert result["open_lot_count"] == 1
    assert result["realized_gain_loss"] == "88.00"
    assert result["unrealized_gain_loss"] == "36.00"
    assert result["realized_lots"][0]["units"] == "5"
    assert result["realized_lots"][0]["holding_period_days"] == 517
    assert result["realized_lots"][1]["units"] == "1"
    assert result["open_lots"][0]["units"] == "4"
    assert result["tax_status"] == "TAX_RULES_NOT_APPLIED"


def test_fifo_capital_gains_rejects_redemptions_exceeding_available_lots():
    transactions = [
        {
            "id": 1, "scheme_code": 120002, "transaction_type": "BUY",
            "transaction_date": date(2025, 1, 1), "units": "2",
            "amount": "200", "charges": "0",
        },
        {
            "id": 2, "scheme_code": 120002, "transaction_type": "SELL",
            "transaction_date": date(2025, 2, 1), "units": "3",
            "amount": "330", "charges": "0",
        },
    ]
    with pytest.raises(ValueError, match="exceeds FIFO lots"):
        fifo_capital_gains(transactions, {})

def test_goal_projection_uses_inflation_and_explicit_low_base_high_scenarios():
    result = project_financial_goal(
        target_amount_today=1_000_000,
        current_amount=100_000,
        monthly_contribution=5_000,
        months=120,
        inflation_rate=0.06,
        annual_return_scenarios={"low": 0.04, "base": 0.10, "high": 0.14},
    )
    assert result["inflation_adjusted_target"] > result["target_amount_today"]
    assert result["scenarios"]["low"]["projected_future_value"] < result["scenarios"]["base"]["projected_future_value"]
    assert result["scenarios"]["base"]["projected_future_value"] < result["scenarios"]["high"]["projected_future_value"]
    assert result["scenarios"]["base"]["required_monthly_contribution"] > 0
    assert "not forecasts" in result["methodology"]


def test_goal_projection_handles_zero_return_and_invalid_assumptions():
    result = project_financial_goal(
        target_amount_today=100_000,
        current_amount=10_000,
        monthly_contribution=1_000,
        months=12,
        inflation_rate=0,
        annual_return_scenarios={"zero": 0},
    )
    assert result["inflation_adjusted_target"] == 100_000
    assert result["scenarios"]["zero"]["projected_future_value"] == 22_000
    with pytest.raises(ValueError, match="inflation assumption"):
        project_financial_goal(100_000, 0, 0, 12, 0.25, {"base": 0.1})


def test_period_returns_reject_stale_baseline_nav():
    latest = date(2026, 11, 11)
    target_5y = latest - timedelta(days=365 * 5)
    stale_base = target_5y - timedelta(days=36)
    points = [
        (date(2019, 1, 1), 100.0),
        (stale_base, 120.0),
        (latest, 180.0),
    ]
    result = performance_metrics(points)
    assert result["status"] == "OK"
    assert result["period_returns"]["5Y"] is None


def test_period_returns_accept_nearby_actual_baseline_nav():
    latest = date(2026, 11, 11)
    target_5y = latest - timedelta(days=365 * 5)
    actual_base = target_5y - timedelta(days=3)
    points = [
        (date(2019, 1, 1), 100.0),
        (actual_base, 120.0),
        (latest, 180.0),
    ]
    result = performance_metrics(points)
    assert result["status"] == "OK"
    assert result["period_returns"]["5Y"] == pytest.approx(0.5)


def test_five_year_period_accepts_month_end_sample_within_35_day_window():
    latest = date(2026, 11, 11)
    target_5y = latest - timedelta(days=365 * 5)
    month_end_base = target_5y - timedelta(days=30)
    points = [
        (date(2019, 1, 1), 100.0),
        (month_end_base, 120.0),
        (latest, 180.0),
    ]
    result = performance_metrics(points)
    assert result["status"] == "OK"
    assert result["period_returns"]["5Y"] == pytest.approx(0.5)


def test_period_return_uses_baseline_lookback_without_changing_window_total_return():
    latest = date(2026, 11, 11)
    target_5y = latest - timedelta(days=365 * 5)
    actual_base = target_5y - timedelta(days=30)
    window_points = [
        (target_5y, 120.0),
        (latest, 180.0),
    ]
    baseline_points = [
        (actual_base, 100.0),
        *window_points,
    ]
    result = performance_metrics(
        window_points,
        period_baseline_points=baseline_points,
    )
    assert result["start_date"] == target_5y.isoformat()
    assert result["total_return"] == pytest.approx(0.5)
    assert result["period_returns"]["5Y"] == pytest.approx(0.8)


def test_research_metrics_accepts_actual_baseline_outside_window():
    latest = date(2026, 11, 11)
    target_5y = latest - timedelta(days=365 * 5)
    actual_base = target_5y - timedelta(days=30)
    window_points = [(target_5y, 120.0), (latest, 180.0)]
    baseline_points = [(actual_base, 100.0), *window_points]
    result = research_metrics(
        window_points,
        period_baseline_points=baseline_points,
    )
    assert result["period_returns"]["5Y"] == pytest.approx(0.8)
