from decimal import Decimal

import pytest

from app.portfolio_allocation_intelligence import (
    allocation_drift,
    amc_concentration,
    contribution_plan_preview,
    holdings_overlap_matrix,
    market_cap_allocation,
    parse_market_cap_classification_csv,
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
    assert len(result["sources"]) == 1
    assert result["sources"][0]["classified_security_count"] == 1


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



def test_allocation_drift_validates_complete_target_set_and_calculates_band_status():
    result = allocation_drift([
        {"key": "EQUITY", "min_pct": "40", "target_pct": "50", "max_pct": "60", "actual_value_inr": "300"},
        {"key": "DEBT", "min_pct": "40", "target_pct": "50", "max_pct": "60", "actual_value_inr": "700"},
    ], portfolio_value_inr="1000")
    by_key = {row["key"]: row for row in result["targets"]}
    assert by_key["EQUITY"]["actual_weight_pct"] == "30.0000"
    assert by_key["EQUITY"]["drift_percentage_points"] == "-20.0000"
    assert by_key["EQUITY"]["amount_to_preferred_target_inr"] == "200.00"
    assert by_key["EQUITY"]["status"] == "UNDERWEIGHT"
    assert by_key["DEBT"]["status"] == "OVERWEIGHT"
    with pytest.raises(ValueError, match="reconcile to 100"):
        allocation_drift([
            {"key": "EQUITY", "min_pct": "0", "target_pct": "40", "max_pct": "60", "actual_value_inr": "500"},
        ], portfolio_value_inr="1000")


def test_contribution_plan_is_contribution_only_and_does_not_allocate_to_overweight_segment():
    result = contribution_plan_preview([
        {"key": "EQUITY", "min_pct": "40", "target_pct": "50", "max_pct": "60", "actual_value_inr": "300"},
        {"key": "DEBT", "min_pct": "40", "target_pct": "50", "max_pct": "60", "actual_value_inr": "700"},
    ], portfolio_value_inr="1000", contribution_inr="100")
    by_key = {row["key"]: row for row in result["allocations"]}
    assert by_key["EQUITY"]["contribution_allocation_inr"] == "100.00"
    assert by_key["DEBT"]["contribution_allocation_inr"] == "0.00"
    assert result["allocated_contribution_inr"] == "100.00"
    assert result["plan_type"] == "CONTRIBUTION_ONLY_PREVIEW"
    assert sum(Decimal(row["post_contribution_weight_pct"]) for row in result["post_contribution_allocation"]) == Decimal("100.0000")


def test_contribution_plan_rejects_nonpositive_and_unbounded_contributions():
    targets = [
        {"key": "EQUITY", "min_pct": "0", "target_pct": "50", "max_pct": "100", "actual_value_inr": "500"},
        {"key": "DEBT", "min_pct": "0", "target_pct": "50", "max_pct": "100", "actual_value_inr": "500"},
    ]
    with pytest.raises(ValueError, match="positive"):
        contribution_plan_preview(targets, portfolio_value_inr="1000", contribution_inr="0")



def test_market_cap_classification_csv_parser_is_strict_and_normalizes_bucket_labels():
    rows = parse_market_cap_classification_csv(
        "ISIN,Market Cap Bucket,Effective From,Effective To,Source As Of Date\n"
        "INE002A01018,Large,2026-01-01,,2026-10-31\n"
        "INE009A01021,Mid Cap,2026-01-01,2026-12-31,2026-10-31\n"
    )
    assert len(rows) == 2
    assert rows[0]["market_cap_bucket"] == "LARGE_CAP"
    assert rows[1]["market_cap_bucket"] == "MID_CAP"
    assert rows[0]["effective_to"] is None


def test_market_cap_classification_csv_parser_rejects_invalid_isin_duplicate_and_bucket():
    with pytest.raises(ValueError, match="invalid ISIN"):
        parse_market_cap_classification_csv(
            "ISIN,Market Cap Bucket,Effective From,Source As Of Date\n"
            "BAD,Large,2026-01-01,2026-10-31\n"
        )
    with pytest.raises(ValueError, match="duplicate ISIN"):
        parse_market_cap_classification_csv(
            "ISIN,Market Cap Bucket,Effective From,Source As Of Date\n"
            "INE002A01018,Large,2026-01-01,2026-10-31\n"
            "INE002A01018,Mid,2026-01-01,2026-10-31\n"
        )
    with pytest.raises(ValueError, match="unsupported"):
        parse_market_cap_classification_csv(
            "ISIN,Market Cap Bucket,Effective From,Source As Of Date\n"
            "INE002A01018,MEGA_CAP,2026-01-01,2026-10-31\n"
        )



def test_overlap_matrix_has_a_hard_fund_count_limit():
    funds = [
        {"scheme_code": str(index), "portfolio_value_inr": "1", "disclosure_coverage_pct": "100", "holdings": []}
        for index in range(201)
    ]
    with pytest.raises(ValueError, match="limited to 200"):
        holdings_overlap_matrix(funds)


def test_holdings_disclosure_coverage_uses_positive_isin_weight_over_all_positive_weight():
    from app.portfolio_allocation_intelligence import holdings_disclosure_coverage

    assert holdings_disclosure_coverage([
        {"is_isin": True, "weight_pct": "70"},
        {"is_isin": False, "weight_pct": "20"},
        {"is_isin": False, "weight_pct": "10"},
        {"is_isin": True, "weight_pct": "-5"},
    ]) == "70.0000"


def test_holdings_disclosure_coverage_returns_none_without_positive_reported_weight():
    from app.portfolio_allocation_intelligence import holdings_disclosure_coverage

    assert holdings_disclosure_coverage([
        {"is_isin": True, "weight_pct": "0"},
        {"is_isin": False, "weight_pct": "-2"},
    ]) is None
