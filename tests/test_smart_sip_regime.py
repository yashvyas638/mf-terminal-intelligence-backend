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



def test_invalid_regime_thresholds_are_rejected():
    need, budget = inputs()
    invalid = {**CONFIG, "volatility_ceiling_pct": float("nan")}
    try:
        assess_smart_sip_regime(
            observations(), as_of=date(2026, 11, 18),
            portfolio_need=need, risk_budget=budget, config=invalid,
        )
    except ValueError as exc:
        assert "finite number" in str(exc)
    else:
        raise AssertionError("non-finite regime thresholds must be rejected")


def test_non_finite_tri_and_malformed_provenance_hashes_are_rejected():
    rows = observations()
    rows[-1]["tri"] = float("nan")
    rows[-2]["tri"] = float("inf")
    rows[-3]["source_hash"] = "not-a-sha256"
    result = assess_smart_sip_regime(
        rows, as_of=date(2026, 11, 18),
        portfolio_need=inputs()[0], risk_budget=inputs()[1], config=CONFIG,
    )
    assert result["evidence"]["rejected_observation_count"] == 3
    assert result["evidence"]["latest_observation_date"] == rows[-4]["date"]
    assert not result["topup_eligible"]

def test_non_finite_derived_signals_are_withheld():
    rows = observations()
    # This valid positive TRI value makes the subsequent return and momentum
    # ratio overflow even though every individual observation is finite.
    rows[-64]["tri"] = 1e-308
    result = assess_smart_sip_regime(
        rows, as_of=date(2026, 11, 18),
        portfolio_need=inputs()[0], risk_budget=inputs()[1], config=CONFIG,
    )
    assert result["status"] == "NOT_ASSESSED"
    assert result["market_opportunity"]["reason"] == "INVALID_DERIVED_SIGNAL"
    assert result["signals"] == {}
    assert not result["topup_eligible"]
    assert result["decision"] == "CONTINUE_PLANNED_SIP"


def test_smart_sip_requires_an_explicit_positive_budget_amount_for_api_approval(monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main

    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    for name in (
        "SMART_SIP_MAX_OBSERVATION_AGE_DAYS",
        "SMART_SIP_MIN_OBSERVATIONS_52W",
        "SMART_SIP_MIN_OBSERVATIONS_3Y",
        "SMART_SIP_DRAWDOWN_TOPUP_THRESHOLD_PCT",
        "SMART_SIP_MOMENTUM_FLOOR_PCT",
        "SMART_SIP_VOLATILITY_CEILING_PCT",
        "SMART_SIP_ANNUALISATION_DAYS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(main, "portfolio_valuation", lambda *_: {
        "valuation_date": "2026-11-18",
        "valuation_status": "COMPLETE",
        "valuation_freshness": "FRESH",
    })
    monkeypatch.setattr(main, "get_portfolio_allocation_drift", lambda *_: {
        "status": "AVAILABLE",
        "valuation_date": "2026-11-18",
        "effective_from": "2026-01-01",
        "target_version": 1,
        "targets": [{"key": "EQUITY", "status": "UNDERWEIGHT"}],
    })

    client = TestClient(main.app)
    headers = {"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"}
    base = {
        "benchmark_code": "NIFTY_TEST_TRI",
        "dimension": "ASSET_CLASS",
        "additional_contribution_budget_approved": True,
    }
    without_amount = client.post("/v1/portfolios/123/smart-sip/preview", headers=headers, json=base)
    assert without_amount.status_code == 200
    assert without_amount.json()["risk_budget"]["allowed"] is False
    assert without_amount.json()["topup_eligible"] is False

    with_amount = client.post(
        "/v1/portfolios/123/smart-sip/preview",
        headers=headers,
        json={**base, "additional_contribution_budget_inr": "5000"},
    )
    assert with_amount.status_code == 200
    assert with_amount.json()["risk_budget"]["allowed"] is True
    assert with_amount.json()["risk_budget"]["max_additional_contribution_inr"] == "5000"
    assert with_amount.json()["topup_eligible"] is False


def test_smart_sip_withholds_portfolio_need_when_valuation_is_stale(monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main

    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    for name in (
        "SMART_SIP_MAX_OBSERVATION_AGE_DAYS",
        "SMART_SIP_MIN_OBSERVATIONS_52W",
        "SMART_SIP_MIN_OBSERVATIONS_3Y",
        "SMART_SIP_DRAWDOWN_TOPUP_THRESHOLD_PCT",
        "SMART_SIP_MOMENTUM_FLOOR_PCT",
        "SMART_SIP_VOLATILITY_CEILING_PCT",
        "SMART_SIP_ANNUALISATION_DAYS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(main, "portfolio_valuation", lambda *_: {
        "valuation_date": "2026-11-18",
        "valuation_status": "COMPLETE",
        "valuation_freshness": "STALE",
    })
    monkeypatch.setattr(main, "get_portfolio_allocation_drift", lambda *_: {
        "status": "AVAILABLE",
        "valuation_date": "2026-11-18",
        "effective_from": "2026-01-01",
        "target_version": 1,
        "targets": [{"key": "EQUITY", "status": "UNDERWEIGHT"}],
    })

    client = TestClient(main.app)
    response = client.post(
        "/v1/portfolios/123/smart-sip/preview",
        headers={"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"},
        json={"benchmark_code": "NIFTY_TEST_TRI", "dimension": "ASSET_CLASS"},
    )

    assert response.status_code == 200
    need = response.json()["portfolio_need"]
    assert need["status"] == "WITHHELD"
    assert need["verified"] is False
    assert need["underweight_buckets"] == []
    assert response.json()["topup_eligible"] is False
