from decimal import Decimal

import pytest

from app.portfolio_allocation_intelligence import (
    amc_concentration,
    holdings_overlap_matrix,
    portfolio_allocation,
)


def test_portfolio_allocation_reconciles_market_value_and_preserves_unknown_taxonomy():
    result = portfolio_allocation([
        {"scheme_code": "1", "scheme_name": "Fund A", "market_value_inr": "600", "amc": "AMC A", "category_group": "Equity", "asset_class": "Equity"},
        {"scheme_code": "2", "scheme_name": "Fund B", "market_value_inr": "300", "amc": "AMC A", "category_group": "Debt", "asset_class": "Debt"},
        {"scheme_code": "3", "scheme_name": "Fund C", "market_value_inr": "100", "amc": None},
    ])
    assert result["portfolio_market_value_inr"] == "1000.00"
    assert sum(Decimal(x["portfolio_weight_pct"]) for x in result["by_category"]) == Decimal("100.0000")
    assert result["by_amc"][0]["name"] == "AMC A"
    assert result["by_amc"][0]["portfolio_weight_pct"] == "90.0000"
    assert result["data_quality"]["unclassified_scheme_count"] == 1


def test_portfolio_allocation_rejects_duplicate_schemes_negative_and_zero_total():
    base = {"scheme_code": "1", "market_value_inr": "10"}
    with pytest.raises(ValueError, match="unique"):
        portfolio_allocation([base, base])
    with pytest.raises(ValueError, match="negative"):
        portfolio_allocation([{"scheme_code": "1", "market_value_inr": "-1"}])
    with pytest.raises(ValueError, match="positive"):
        portfolio_allocation([{"scheme_code": "1", "market_value_inr": "0"}])


def test_amc_concentration_uses_values_and_calculates_hhi_and_effective_count():
    result = amc_concentration([
        {"scheme_code": "1", "market_value_inr": "900", "amc": "A"},
        {"scheme_code": "2", "market_value_inr": "50", "amc": "B"},
        {"scheme_code": "3", "market_value_inr": "50", "amc": "C"},
    ])
    assert result["top_1_amc_weight_pct"] == "90.0000"
    assert result["top_3_amc_weight_pct"] == "100.0000"
    assert Decimal(result["hhi_points"]) == Decimal("8150.00")
    assert Decimal(result["effective_amc_count"]) == Decimal("1.2270")


def test_overlap_is_symmetric_and_uses_minimum_exposure_per_common_isin():
    result = holdings_overlap_matrix([
        {"scheme_code": "A", "portfolio_value_inr": "1000", "disclosure_coverage_pct": "100", "holdings": [
            {"security_id": "INE000000001", "is_isin": True, "weight_pct": "20"},
            {"security_id": "INE000000002", "is_isin": True, "weight_pct": "10"},
        ]},
        {"scheme_code": "B", "portfolio_value_inr": "500", "disclosure_coverage_pct": "100", "holdings": [
            {"security_id": "INE000000001", "is_isin": True, "weight_pct": "30"},
            {"security_id": "INE000000003", "is_isin": True, "weight_pct": "10"},
        ]},
    ])
    pair = result["pairs"][0]
    assert pair["overlap_inr"] == "150.00"
    assert pair["overlap_pct_of_scheme_a_nav"] == "15.0000"
    assert pair["overlap_pct_of_scheme_b_nav"] == "30.0000"
    assert pair["common_isin_count"] == 1


def test_portfolio_duplication_counts_shared_exposure_once_not_pairwise_sum():
    result = holdings_overlap_matrix([
        {"scheme_code": "A", "portfolio_value_inr": "100", "disclosure_coverage_pct": "100", "holdings": [
            {"security_id": "INE000000001", "is_isin": True, "weight_pct": "50"},
        ]},
        {"scheme_code": "B", "portfolio_value_inr": "100", "disclosure_coverage_pct": "100", "holdings": [
            {"security_id": "INE000000001", "is_isin": True, "weight_pct": "30"},
        ]},
        {"scheme_code": "C", "portfolio_value_inr": "100", "disclosure_coverage_pct": "100", "holdings": [
            {"security_id": "INE000000001", "is_isin": True, "weight_pct": "20"},
        ]},
    ])
    duplication = result["portfolio_duplication"]
    assert duplication["duplicated_exposure_inr"] == "50.00"
    assert duplication["gross_positive_lookthrough_exposure_inr"] == "100.00"
    assert duplication["duplicated_share_of_gross_positive_lookthrough_pct"] == "50.0000"


def test_non_isin_rows_are_never_cross_matched_and_missing_coverage_withholds_pair():
    result = holdings_overlap_matrix([
        {"scheme_code": "A", "portfolio_value_inr": "100", "disclosure_coverage_pct": None, "holdings": [
            {"security_id": "NONISIN:abc", "is_isin": False, "weight_pct": "50"},
            {"security_id": "INE000000001", "is_isin": True, "weight_pct": "10"},
        ]},
        {"scheme_code": "B", "portfolio_value_inr": "100", "disclosure_coverage_pct": "100", "holdings": [
            {"security_id": "NONISIN:abc", "is_isin": False, "weight_pct": "50"},
            {"security_id": "INE000000001", "is_isin": True, "weight_pct": "10"},
        ]},
    ])
    pair = result["pairs"][0]
    assert pair["status"] == "PARTIAL_COVERAGE_UNKNOWN"
    assert pair["overlap_inr"] == "10.00"
    assert pair["common_isin_count"] == 1


def test_overlap_rejects_invalid_coverage_and_nonfinite_inputs():
    with pytest.raises(ValueError, match="coverage"):
        holdings_overlap_matrix([{"scheme_code": "A", "portfolio_value_inr": "1", "disclosure_coverage_pct": "101"}])
    with pytest.raises(ValueError, match="finite"):
        portfolio_allocation([{"scheme_code": "A", "market_value_inr": "NaN"}])
