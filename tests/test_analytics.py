from datetime import date, timedelta

from app.analytics import max_drawdown, performance_metrics, xirr


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
