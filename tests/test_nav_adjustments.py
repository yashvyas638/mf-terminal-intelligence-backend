from datetime import date

import pytest

from app.nav_adjustments import (
    NAV_ADJUSTMENT_REGISTRY_VERSION,
    apply_nav_quality_gates,
    apply_verified_nav_adjustments,
    detect_nav_discontinuities,
)


def test_verified_icici_overnight_unit_consolidation_is_applied_to_pre_event_navs():
    points = [
        (date(2022, 7, 29), 100.3737),
        (date(2022, 8, 30), 1004.3319),
        (date(2022, 9, 30), 1007.5),
    ]

    adjusted, applied = apply_verified_nav_adjustments(145536, points)

    assert adjusted[0][1] == pytest.approx(1003.737)
    assert adjusted[1][1] == pytest.approx(1004.3319)
    assert len(applied) == 1
    assert applied[0]["effective_date"] == "2022-08-17"
    assert applied[0]["factor"] == 10.0
    assert applied[0]["source_urls"]
    assert detect_nav_discontinuities(adjusted) == []


def test_unverified_nav_level_change_is_flagged_without_mutating_raw_nav():
    points = [
        (date(2022, 1, 31), 100.0),
        (date(2022, 2, 28), 10.0),
        (date(2022, 3, 31), 10.1),
    ]

    adjusted, applied = apply_verified_nav_adjustments(999999, points)
    flags = detect_nav_discontinuities(adjusted)

    assert adjusted == points
    assert applied == []
    assert len(flags) == 1
    assert flags[0]["type"] == "unverified_nav_level_discontinuity"
    assert flags[0]["ratio"] == pytest.approx(0.1)
    assert flags[0]["nav_date"] == date(2022, 2, 28)


def test_unverified_old_jump_only_suppresses_affected_period_and_window_metrics():
    latest_date = date(2026, 11, 11)
    event = {
        "type": "unverified_nav_level_discontinuity",
        "previous_date": date(2022, 7, 31),
        "nav_date": date(2022, 8, 31),
        "previous_nav": 100.0,
        "nav_value": 10.0,
        "ratio": 0.1,
        "gap_days": 31,
    }
    metrics = {
        "period_returns": {
            "1M": 0.004,
            "3M": 0.012,
            "6M": 0.024,
            "1Y": 0.055,
            "3Y": 0.18,
            "5Y": 0.42,
        },
        "total_return": 0.42,
        "cagr": 0.073,
        "annualized_volatility": 0.12,
        "sharpe_ratio": 0.5,
        "sortino_ratio": 0.7,
        "max_drawdown": -0.08,
        "positive_month_rate": 0.7,
        "rolling_1y": {"status": "OK", "observations": 48, "positive_window_rate": 0.8},
        "monthly_returns": [{"month": "2022-08", "return": -0.9}],
    }

    short_window, short_status, short_flags = apply_nav_quality_gates(
        dict(metrics),
        latest_date=latest_date,
        window_days=365,
        discontinuities=[event],
    )
    assert short_status == "REVIEW_REQUIRED"
    assert short_flags[0]["affected_periods"] == ["5Y"]
    assert short_window["period_returns"]["1M"] == pytest.approx(0.004)
    assert short_window["period_returns"]["1Y"] == pytest.approx(0.055)
    assert short_window["period_returns"]["5Y"] is None
    assert short_window["annualized_volatility"] == pytest.approx(0.12)

    long_window, long_status, long_flags = apply_nav_quality_gates(
        dict(metrics),
        latest_date=latest_date,
        window_days=1825,
        discontinuities=[event],
    )
    assert long_status == "REVIEW_REQUIRED"
    assert long_flags[0]["affects_window_metrics"] is True
    assert long_window["total_return"] is None
    assert long_window["cagr"] is None
    assert long_window["annualized_volatility"] is None
    assert long_window["max_drawdown"] is None
    assert long_window["rolling_1y"]["status"] == "REVIEW_REQUIRED"
    assert long_window["monthly_returns"] == []


def test_snapshot_adjustment_registry_is_versioned():
    assert NAV_ADJUSTMENT_REGISTRY_VERSION



def test_mixed_frequency_window_suppresses_daily_risk_statistics_only():
    latest_date = date(2022, 2, 28)
    metrics = {
        "period_returns": {"1M": 0.01, "3M": 0.02, "6M": 0.03, "1Y": 0.04, "3Y": None, "5Y": None},
        "total_return": 0.02,
        "cagr": 0.08,
        "annualized_volatility": 0.11,
        "volatility": 0.11,
        "sharpe_ratio": 0.5,
        "sortino_ratio": 0.7,
        "max_drawdown": -0.02,
        "positive_month_rate": 0.6,
        "rolling_1y": {"status": "OK", "observations": 12, "positive_window_rate": 0.8},
        "monthly_returns": [{"month": "2022-02", "return": 0.01}],
    }

    result, quality_status, flags = apply_nav_quality_gates(
        metrics,
        latest_date=latest_date,
        window_days=3650,
        discontinuities=[],
        window_points=[
            (date(2022, 1, 1), 100.0),
            (date(2022, 1, 31), 101.0),
            (date(2022, 2, 28), 102.0),
        ],
    )

    assert quality_status == "REVIEW_REQUIRED"
    assert result["risk_statistics_status"] == "MIXED_FREQUENCY_NOT_COMPARABLE"
    assert result["annualized_volatility"] is None
    assert result["volatility"] is None
    assert result["sharpe_ratio"] is None
    assert result["sortino_ratio"] is None
    assert result["max_drawdown"] is None
    assert result["total_return"] == pytest.approx(0.02)
    assert result["period_returns"]["1Y"] == pytest.approx(0.04)
    assert flags[0]["type"] == "mixed_frequency_risk_series"
