from datetime import date, timedelta

import pytest

from app.analytics import max_drawdown, performance_metrics, rolling_return_series, research_metrics, xirr


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
    points = [(start + timedelta(days=30 * i), 100 + 2 * i) for i in range(50)]
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
    points = [(start + timedelta(days=30 * i), 100 + 2 * i) for i in range(50)]
    result = research_metrics(points)
    assert result["status"] == "OK"
    assert result["positive_month_rate"] == 1.0
    assert "consistency_note" in result
    assert result["rolling_1y"]["status"] == "OK"
