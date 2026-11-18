from decimal import Decimal

import pytest

from app.portfolio_allocation_intelligence import (
    amc_concentration,
    holdings_overlap_matrix,
    market_cap_allocation,
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



def test_scheme_weight_inside_segment_is_distinct_from_total_portfolio_weight():
    result = portfolio_allocation([
        {"scheme_code": "1", "market_value_inr": "300", "category_group": "Equity", "sub_category": "Large Cap"},
        {"scheme_code": "2", "market_value_inr": "100", "category_group": "Equity", "sub_category": "Mid Cap"},
        {"scheme_code": "3", "market_value_inr": "600", "category_group": "Debt", "sub_category": "Corporate Bond"},
    ])
    by_code = {row["scheme_code"]: row for row in result["schemes"]}
    assert by_code["1"]["portfolio_weight_pct"] == "30.0000"
    assert by_code["1"]["segment_weight_pct"] == "75.0000"
    assert by_code["2"]["segment_weight_pct"] == "25.0000"


def test_market_cap_lookthrough_uses_verified_effective_dated_mapping_and_keeps_unknown_visible():
    result = market_cap_allocation(
        [
            {"security_id": "INE000000001", "is_isin": True, "lookthrough_value": "400"},
            {"security_id": "INE000000002", "is_isin": True, "lookthrough_value": "300"},
            {"security_id": "NONISIN:cash", "is_isin": False, "lookthrough_value": "100"},
        ],
        [
            {"security_id": "INE000000001", "market_cap_bucket": "LARGE_CAP", "effective_from": "2026-01-01", "source_as_of_date": "2026-10-31", "source_url": "https://example.com/source-a", "source_sha256": "a" * 64, "verification_status": "VERIFIED"},
            {"security_id": "INE000000002", "market_cap_bucket": "MID_CAP", "effective_from": "2026-01-01", "source_as_of_date": "2025-01-01", "source_url": "https://example.com/source-b", "source_sha256": "b" * 64, "verification_status": "VERIFIED"},
            {"security_id": "INE000000002", "market_cap_bucket": "SMALL_CAP", "effective_from": "2026-01-01", "source_as_of_date": "2026-10-31", "source_url": "https://example.com/unverified", "source_sha256": "c" * 64, "verification_status": "PENDING"},
        ],
        as_of_date="2026-11-01",
        portfolio_value_inr="1000",
        max_classification_age_days=180,
    )
    assert result["classified_exposure_inr"] == "400.00"
    assert result["classified_coverage_of_positive_lookthrough_pct"] == "50.0000"
    assert result["classified_distribution"][0]["market_cap_bucket"] == "LARGE_CAP"
    unknown = {row["reason"]: row["exposure_inr"] for row in result["unclassified_exposure"]}
    assert unknown["UNCLASSIFIED_STALE_MAPPING"] == "300.00"
    assert unknown["UNCLASSIFIED_NON_ISIN"] == "100.00"


def test_market_cap_rejects_conflicting_effective_classifications_and_bad_provenance():
    base = {
        "security_id": "INE000000001", "is_isin": True,
        "effective_from": "2026-01-01", "source_as_of_date": "2026-10-01",
        "source_url": "https://example.com/source", "source_sha256": "a" * 64,
        "verification_status": "VERIFIED",
    }
    with pytest.raises(ValueError, match="conflicting"):
        market_cap_allocation(
            [{"security_id": "INE000000001", "is_isin": True, "lookthrough_value": "100"}],
            [{**base, "market_cap_bucket": "LARGE_CAP"}, {**base, "market_cap_bucket": "MID_CAP", "source_sha256": "b" * 64}],
            as_of_date="2026-11-01", portfolio_value_inr="100",
        )
    with pytest.raises(ValueError, match="SHA-256"):
        market_cap_allocation(
            [{"security_id": "INE000000001", "is_isin": True, "lookthrough_value": "100"}],
            [{**base, "market_cap_bucket": "LARGE_CAP", "source_sha256": "bad"}],
            as_of_date="2026-11-01", portfolio_value_inr="100",
        )
