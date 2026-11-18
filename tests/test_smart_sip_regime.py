from datetime import date, timedelta
from app.smart_sip_regime import assess_smart_sip_regime

CONFIG = {
    "max_observation_age_days": 3, "min_observations_52w": 30,
    "min_observations_3y": 30, "drawdown_topup_threshold_pct": 10,
    "momentum_floor_pct": -50, "volatility_ceiling_pct": 100,
    "annualisation_days": 252,
}


def observations(count=800, stale_days=0, verified=True):
    end = date(2026, 11, 18) - timedelta(days=stale_days)
    rows = []
    for index in range(count):
        day = end - timedelta(days=count - index - 1)
        value = 1000 + index * 0.5
        if index > count - 35:
            value -= (index - (count - 35)) * 3
        rows.append({"date": day.isoformat(), "tri": value,
                     "source_id": "NIFTY_TEST_TRI", "source_hash": "a" * 64,
                     "source_verified": verified})
    return rows


def inputs():
    return {"status": "UNDERWEIGHT", "verified": True}, {"allowed": True}


def test_stale_and_unverified_benchmark_withhold_market_signal():
    need, budget = inputs()
    stale = assess_smart_sip_regime(observations(stale_days=8), as_of=date(2026, 11, 18),
        portfolio_need=need, risk_budget=budget, config=CONFIG)
    unverified = assess_smart_sip_regime(observations(verified=False), as_of=date(2026, 11, 18),
        portfolio_need=need, risk_budget=budget, config=CONFIG)
    assert stale["status"] == "NOT_ASSESSED" and not stale["topup_eligible"]
    assert unverified["status"] == "NOT_ASSESSED"


def test_market_signal_cannot_override_portfolio_need_or_risk_budget():
    need, budget = inputs()
    no_need = assess_smart_sip_regime(observations(), as_of=date(2026, 11, 18),
        portfolio_need={"status": "WITHHELD", "verified": False}, risk_budget=budget, config=CONFIG)
    no_budget = assess_smart_sip_regime(observations(), as_of=date(2026, 11, 18),
        portfolio_need=need, risk_budget={"allowed": False}, config=CONFIG)
    assert not no_need["topup_eligible"] and not no_budget["topup_eligible"]
    assert no_need["decision"] == "CONTINUE_PLANNED_SIP"


def test_duplicate_dates_are_not_counted_as_evidence():
    rows = observations()
    rows.append(dict(rows[-1]))
    result = assess_smart_sip_regime(rows, as_of=date(2026, 11, 18),
        portfolio_need=inputs()[0], risk_budget=inputs()[1], config=CONFIG)
    assert result["evidence"]["duplicate_date_count"] == 1
    assert not result["topup_eligible"]
