import hashlib
import json

from app.twt_monthly_report import (
    compare_monthly_reports,
    decode_verified_snapshot,
    is_month_end_valuation_date,
    select_latest_distinct_months,
)


def _report(valuation_date, value, scheme_value, scheme_weight, market_cap_status="PARTIAL_CLASSIFICATION_COVERAGE"):
    return {
        "valuation": {"valuation_date": valuation_date, "current_value": str(value)},
        "allocation_intelligence": {
            "status": "AVAILABLE",
            "allocation": {
                "schemes": [{
                    "scheme_code": "1001", "market_value_inr": str(scheme_value),
                    "portfolio_weight_pct": str(scheme_weight),
                }],
                "by_category": [{"name": "Equity", "market_value_inr": str(scheme_value), "portfolio_weight_pct": str(scheme_weight)}],
                "by_sub_category": [{"name": "Large Cap", "market_value_inr": str(scheme_value), "portfolio_weight_pct": str(scheme_weight)}],
                "by_asset_class": [{"name": "Equity", "market_value_inr": str(scheme_value), "portfolio_weight_pct": str(scheme_weight)}],
            },
            "amc_concentration": {"amcs": [{"name": "AMC A", "market_value_inr": str(scheme_value), "portfolio_weight_pct": str(scheme_weight)}], "top_1_amc_weight_pct": str(scheme_weight), "top_3_amc_weight_pct": str(scheme_weight), "top_5_amc_weight_pct": str(scheme_weight), "hhi_points": "5000", "effective_amc_count": "2"},
            "evidence": {"nav_coverage": {"fresh_nav_coverage_pct": "100.0000"}},
        },
        "lookthrough": {
            "coverage": {"status": "COMPLETE", "fresh_covered_weight_pct": "100.0000"},
            "sector_exposure": [{"sector": "Financials", "lookthrough_value": str(scheme_value), "portfolio_weight_pct": str(scheme_weight)}],
        },
        "overlap_intelligence": {
            "status": "AVAILABLE",
            "pairs": [{
                "scheme_a": "1001", "scheme_b": "1002",
                "overlap_inr": "40.00", "overlap_pct_of_scheme_a_nav": "4.0000",
                "overlap_pct_of_scheme_b_nav": "8.0000",
            }],
            "portfolio_duplication": {"duplicated_exposure_inr": "50.00"},
            "disclosure_health": {"disclosure_scheme_coverage_pct": "100.0000"},
        },
        "market_cap_intelligence": {
            "status": market_cap_status,
            "classified_coverage_of_positive_lookthrough_pct": "80.0000",
            "classified_distribution": [{
                "market_cap_bucket": "LARGE_CAP", "exposure_inr": str(scheme_value),
                "weight_of_total_portfolio_pct": str(scheme_weight),
            }],
            "unclassified_exposure": [{
                "reason": "UNCLASSIFIED_STALE_MAPPING", "exposure_inr": "20.00",
                "weight_of_total_portfolio_pct": "2.0000",
            }],
        },
    }


def test_month_selection_uses_newest_snapshot_per_distinct_valuation_month():
    snapshots = [
        {"report_id": 3, "generated_at": "2026-11-02", "report": _report("2026-10-30", 1000, 700, 70)},
        {"report_id": 2, "generated_at": "2026-10-20", "report": _report("2026-10-19", 900, 600, 66.6667)},
        {"report_id": 1, "generated_at": "2026-10-01", "report": _report("2026-09-30", 800, 500, 62.5)},
    ]
    selected = select_latest_distinct_months(snapshots)
    assert [item["period"] for item in selected] == ["2026-10", "2026-09"]
    assert [item["report_id"] for item in selected] == [3, 1]


def test_monthly_comparison_reports_rupee_and_percentage_point_changes():
    previous = {"period": "2026-09", "report": _report("2026-09-30", 800, 500, 62.5)}
    current = {"period": "2026-10", "report": _report("2026-10-30", 1000, 700, 70)}
    result = compare_monthly_reports(previous, current)
    assert result["status"] == "AVAILABLE"
    assert result["comparisons"]["portfolio_value"]["change_inr"] == "200"
    scheme = result["comparisons"]["scheme"]["items"][0]["metrics"]
    assert scheme["market_value_inr"]["change_inr"] == "200"
    assert scheme["portfolio_weight_pct"]["change_percentage_points"] == "7.5"
    category = result["comparisons"]["category"]["items"][0]["metrics"]
    assert category["market_value_inr"]["change_inr"] == "200"
    assert category["portfolio_weight_pct"]["change_percentage_points"] == "7.5"
    market_cap = result["comparisons"]["market_cap"]["items"]
    assert any(row["key"] == "UNCLASSIFIED:UNCLASSIFIED_STALE_MAPPING" for row in market_cap)
    assert result["comparisons"]["overlap_pairs"]["items"][0]["metrics"]["overlap_inr"]["change_inr"] == "0.00"
    assert result["comparisons"]["overlap_pairs"]["items"][0]["metrics"]["overlap_pct_of_scheme_a_nav"]["change_percentage_points"] == "0.0000"
    assert result["comparisons"]["portfolio_duplication"]["change_inr"] == "0.00"
    assert result["comparisons"]["amc_concentration_metrics"]["top_1_amc_weight_pct"]["change_percentage_points"] == "7.5"
    assert result["comparisons"]["data_coverage"]["market_cap_classification"]["change_percentage_points"] == "0.0000"


def test_monthly_comparison_withholds_market_cap_when_either_period_is_unavailable():
    previous = {"period": "2026-09", "report": _report("2026-09-30", 800, 500, 62.5, "WITHHELD")}
    current = {"period": "2026-10", "report": _report("2026-10-30", 1000, 700, 70)}
    result = compare_monthly_reports(previous, current)
    assert result["comparisons"]["market_cap"]["status"] == "WITHHELD_OR_NOT_COMPARABLE"


def test_month_selection_excludes_mid_month_valuation_snapshots():
    snapshots = [
        {"report_id": 9, "generated_at": "2026-11-10", "report": _report("2026-11-10", 1000, 700, 70)},
        {"report_id": 8, "generated_at": "2026-10-15", "report": _report("2026-10-15", 900, 600, 66.6667)},
    ]
    assert select_latest_distinct_months(snapshots) == []



def test_month_end_window_includes_final_seven_days_only():
    assert is_month_end_valuation_date("2026-10-31")
    assert is_month_end_valuation_date("2026-10-25")
    assert not is_month_end_valuation_date("2026-10-24")
    assert not is_month_end_valuation_date("2026-10-15")
    assert is_month_end_valuation_date("2026-11-24")
    assert not is_month_end_valuation_date("2026-11-23")
    assert is_month_end_valuation_date("2024-02-23")
    assert not is_month_end_valuation_date("2024-02-22")
    assert not is_month_end_valuation_date("not-a-date")
    assert not is_month_end_valuation_date("2026-10-31", window_days=0)



def test_month_selection_does_not_compare_across_a_missing_calendar_month():
    snapshots = [
        {"report_id": 3, "generated_at": "2026-12-31", "report": _report("2026-12-31", 1200, 800, 66.7)},
        {"report_id": 1, "generated_at": "2026-10-31", "report": _report("2026-10-31", 900, 600, 66.7)},
    ]

    selected = select_latest_distinct_months(snapshots)

    assert [item["period"] for item in selected] == ["2026-12"]



def test_snapshot_json_is_decoded_only_when_sha256_matches():
    payload = {"valuation": {"valuation_date": "2026-10-31", "current_value": "100"}}
    content = json.dumps(payload, sort_keys=True)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

    assert decode_verified_snapshot(content, digest) == payload
    assert decode_verified_snapshot(content, "0" * 64) is None
    assert decode_verified_snapshot("{broken", digest) is None

def test_monthly_overlap_pair_identity_is_order_independent_and_keeps_directional_denominators():
    previous_report = _report("2026-09-30", 800, 500, 62.5)
    current_report = _report("2026-10-30", 900, 600, 66.6667)
    previous_report["overlap_intelligence"]["pairs"] = [{
        "scheme_a": "1001", "scheme_b": "1002",
        "overlap_inr": "40.00",
        "overlap_pct_of_scheme_a_nav": "4.0000",
        "overlap_pct_of_scheme_b_nav": "8.0000",
    }]
    current_report["overlap_intelligence"]["pairs"] = [{
        "scheme_a": "1002", "scheme_b": "1001",
        "overlap_inr": "45.00",
        "overlap_pct_of_scheme_a_nav": "9.0000",
        "overlap_pct_of_scheme_b_nav": "4.5000",
    }]

    result = compare_monthly_reports(
        {"period": "2026-09", "report": previous_report},
        {"period": "2026-10", "report": current_report},
    )
    pair_rows = result["comparisons"]["overlap_pairs"]["items"]

    assert len(pair_rows) == 1
    pair = pair_rows[0]
    assert pair["key"] == "1001:1002"
    assert pair["presence_status"] == "CONTINUING"
    assert pair["metrics"]["overlap_inr"]["change_inr"] == "5.00"
    assert pair["metrics"]["overlap_pct_of_scheme_a_nav"]["previous"] == "4.0000"
    assert pair["metrics"]["overlap_pct_of_scheme_a_nav"]["current"] == "4.5000"
    assert pair["metrics"]["overlap_pct_of_scheme_b_nav"]["previous"] == "8.0000"
    assert pair["metrics"]["overlap_pct_of_scheme_b_nav"]["current"] == "9.0000"

def test_monthly_risk_comparison_withholds_different_lookback_windows():
    previous_report = _report("2026-09-30", 800, 500, 62.5)
    current_report = _report("2026-10-30", 900, 600, 66.6667)
    previous_report["lookback_days"] = 1095
    current_report["lookback_days"] = 365
    previous_report["risk"] = {"status": "OK", "metrics": {"annualized_volatility": "0.12"}}
    current_report["risk"] = {"status": "OK", "metrics": {"annualized_volatility": "0.18"}}

    result = compare_monthly_reports(
        {"period": "2026-09", "report": previous_report},
        {"period": "2026-10", "report": current_report},
    )

    metric = result["risk_changes"]["annualized_volatility"]
    assert metric["status"] == "WITHHELD_DIFFERENT_OR_MISSING_LOOKBACK"
    assert metric["previous"] is None
    assert metric["current"] is None
    assert metric["change"] is None


def test_monthly_risk_comparison_withholds_stale_nav_risk_inputs():
    previous_report = _report("2026-09-30", 800, 500, 62.5)
    current_report = _report("2026-10-30", 900, 600, 66.6667)
    for report in (previous_report, current_report):
        report["lookback_days"] = 1095
        report["risk"] = {"status": "STALE_NAV", "metrics": {"annualized_volatility": "0.12"}}

    result = compare_monthly_reports(
        {"period": "2026-09", "report": previous_report},
        {"period": "2026-10", "report": current_report},
    )

    assert result["risk_changes"]["annualized_volatility"]["status"] == "WITHHELD_RISK_INPUT_STATUS"



def test_monthly_comparison_withholds_duplicate_scheme_identifiers_instead_of_overwriting():
    previous_report = _report("2026-09-30", 800, 500, 62.5)
    current_report = _report("2026-10-30", 900, 600, 66.6667)
    current_report["allocation_intelligence"]["allocation"]["schemes"].append({
        "scheme_code": "1001", "market_value_inr": "300",
        "portfolio_weight_pct": "33.3333",
    })

    result = compare_monthly_reports(
        {"period": "2026-09", "report": previous_report},
        {"period": "2026-10", "report": current_report},
    )

    assert result["comparisons"]["scheme"]["status"] == "WITHHELD_DUPLICATE_OR_INVALID_KEYS"
    assert result["comparisons"]["scheme"]["items"] == []


def test_monthly_comparison_withholds_missing_category_identifiers():
    previous_report = _report("2026-09-30", 800, 500, 62.5)
    current_report = _report("2026-10-30", 900, 600, 66.6667)
    current_report["allocation_intelligence"]["allocation"]["by_category"].append({
        "name": " ", "market_value_inr": "300", "portfolio_weight_pct": "33.3333",
    })

    result = compare_monthly_reports(
        {"period": "2026-09", "report": previous_report},
        {"period": "2026-10", "report": current_report},
    )

    assert result["comparisons"]["category"]["status"] == "WITHHELD_DUPLICATE_OR_INVALID_KEYS"
    assert result["comparisons"]["category"]["items"] == []
