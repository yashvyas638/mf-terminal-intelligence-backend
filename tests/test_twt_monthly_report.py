from app.twt_monthly_report import compare_monthly_reports, select_latest_distinct_months


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
            "amc_concentration": {"amcs": [{"name": "AMC A", "market_value_inr": str(scheme_value), "portfolio_weight_pct": str(scheme_weight)}]},
        },
        "lookthrough": {
            "coverage": {"status": "COMPLETE"},
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
        },
        "market_cap_intelligence": {
            "status": market_cap_status,
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
    assert result["comparisons"]["portfolio_duplication"]["change_inr"] == "0.00"


def test_monthly_comparison_withholds_market_cap_when_either_period_is_unavailable():
    previous = {"period": "2026-09", "report": _report("2026-09-30", 800, 500, 62.5, "WITHHELD")}
    current = {"period": "2026-10", "report": _report("2026-10-30", 1000, 700, 70)}
    result = compare_monthly_reports(previous, current)
    assert result["comparisons"]["market_cap"]["status"] == "WITHHELD_OR_NOT_COMPARABLE"
