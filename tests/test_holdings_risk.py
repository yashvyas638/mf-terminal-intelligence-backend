import pytest

from app.holdings_risk import security_concentration_metrics


def test_concentration_metrics_use_observed_positive_exposure_denominator():
    result = security_concentration_metrics(
        [
            {"lookthrough_value": "600", "fresh_disclosure_exposure_inr": "600", "stale_disclosure_exposure_inr": "0", "is_isin": True},
            {"lookthrough_value": "300", "fresh_disclosure_exposure_inr": "0", "stale_disclosure_exposure_inr": "300", "is_isin": True},
            {"lookthrough_value": "100", "fresh_disclosure_exposure_inr": "100", "stale_disclosure_exposure_inr": "0", "is_isin": False},
            {"lookthrough_value": "-50", "fresh_disclosure_exposure_inr": "-50", "stale_disclosure_exposure_inr": "0", "is_isin": False},
        ],
        portfolio_value="2000",
        valuation_complete=True,
    )
    assert result["basis"] == "OBSERVED_VERIFIED_DISCLOSURES_ONLY"
    assert result["positive_disclosed_exposure_inr"] == "1000.00"
    assert result["negative_disclosed_exposure_inr"] == "-50.00"
    assert result["fresh_positive_disclosed_exposure_inr"] == "700.00"
    assert result["stale_positive_disclosed_exposure_inr"] == "300.00"
    assert result["top_1_weight_of_observed_positive_pct"] == "60.0000"
    assert result["top_5_weight_of_observed_positive_pct"] == "100.0000"
    assert result["isin_identity_coverage_pct"] == "90.0000"
    assert result["hhi_points"] == "4600.00"
    assert result["effective_security_count"] == "2.1739"
    assert result["observed_positive_exposure_as_pct_of_portfolio"] == "50.0000"


def test_concentration_does_not_claim_full_portfolio_weight_when_valuation_incomplete():
    result = security_concentration_metrics(
        [{"lookthrough_value": "100", "is_isin": True}],
        portfolio_value="0",
        valuation_complete=False,
    )
    assert result["top_1_weight_of_observed_positive_pct"] == "100.0000"
    assert result["observed_positive_exposure_as_pct_of_portfolio"] is None
    assert result["portfolio_value_denominator_available"] is False


def test_empty_disclosures_return_null_concentration_metrics():
    result = security_concentration_metrics(
        [], portfolio_value="1000", valuation_complete=True
    )
    assert result["positive_security_count"] == 0
    assert result["hhi_points"] is None
    assert result["effective_security_count"] is None
    assert result["isin_identity_coverage_pct"] is None


def test_rejects_non_finite_or_negative_portfolio_value():
    with pytest.raises(ValueError, match="finite decimal"):
        security_concentration_metrics(
            [{"lookthrough_value": "NaN", "is_isin": True}],
            portfolio_value="1000",
            valuation_complete=True,
        )
    with pytest.raises(ValueError, match="cannot be negative"):
        security_concentration_metrics(
            [], portfolio_value="-1", valuation_complete=True
        )
