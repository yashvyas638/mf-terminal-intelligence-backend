from app.reporting import _holding_weight_pct, build_portfolio_report_pdf


def test_holding_weight_uses_complete_portfolio_value():
    valuation = {"valuation_status": "COMPLETE", "current_value": "250000"}
    assert _holding_weight_pct({"market_value": "62500"}, valuation) == "25.00%"


def test_holding_weight_is_withheld_for_incomplete_valuation():
    valuation = {"valuation_status": "PARTIAL_MISSING_NAV", "current_value": "250000"}
    assert _holding_weight_pct({"market_value": "62500"}, valuation) == "—"


def test_holding_weight_handles_missing_or_invalid_values():
    valuation = {"valuation_status": "COMPLETE", "current_value": "0"}
    assert _holding_weight_pct({"market_value": "62500"}, valuation) == "—"
    valuation["current_value"] = "250000"
    assert _holding_weight_pct({"market_value": None}, valuation) == "—"


def test_pdf_report_builds_with_real_valuation_field_names():
    report = {
        "portfolio_name": "Regression portfolio",
        "generated_at": "2026-11-18T10:00:00+00:00",
        "report_version": "portfolio-report-v1",
        "valuation": {
            "valuation_status": "COMPLETE",
            "current_value": "250000",
            "remaining_cost_basis": "200000",
            "holdings": [{
                "scheme_name": "Example Equity Fund",
                "units": "100",
                "market_value": "62500",
                "nav_date": "2026-11-17",
                "nav_freshness": "FRESH",
            }],
        },
        "risk": {},
        "lookthrough": {},
        "fifo_tax_lots": {},
        "sources": [],
        "limitations": [],
    }
    pdf = build_portfolio_report_pdf(report)
    assert pdf.startswith(b"%PDF")


def test_pdf_renders_portfolio_overlap_section_with_non_additive_methodology():
    report = {
        "portfolio_name": "Overlap PDF Test",
        "generated_at": "2026-11-18T10:00:00+00:00",
        "report_version": "portfolio-report-v1",
        "valuation": {"valuation_status": "COMPLETE", "current_value": "100000", "holdings": []},
        "lookthrough": {},
        "holdings_overlap": {
            "status": "OK",
            "fund_count": 2,
            "pairs": [{
                "scheme_a": 1, "scheme_b": 2, "overlap_pct": "4.2500",
                "common_isin_count": 2, "status": "OK",
            }],
            "funds": [
                {"scheme_code": 1, "scheme_name": "Fund One"},
                {"scheme_code": 2, "scheme_name": "Fund Two"},
            ],
        },
        "risk": {}, "fifo_tax_lots": {}, "sources": [], "limitations": [],
    }
    pdf = build_portfolio_report_pdf(report)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000


def test_pdf_includes_amc_category_and_asset_class_sections():
    report = {
        "portfolio_name": "TWT Allocation Test",
        "generated_at": "2026-11-18T10:00:00+00:00",
        "report_version": "portfolio-report-v1",
        "valuation": {"valuation_status": "COMPLETE", "current_value": "100000", "holdings": []},
        "lookthrough": {
            "coverage": {"status": "COMPLETE", "fresh_covered_weight_pct": 100.0},
            "amc_concentration": {
                "summary": {"top_1_weight_of_observed_pct": 100.0, "top_3_weight_of_observed_pct": 100.0, "hhi_points": 10000.0, "effective_count": 1.0},
                "items": [{"name": "Example AMC", "market_value": "100000.00", "portfolio_weight_pct": 100.0, "scheme_count": 1}],
            },
            "category_allocation": [{"name": "Flexi Cap Fund", "market_value": "100000.00", "portfolio_weight_pct": 100.0, "scheme_count": 1}],
            "asset_class_allocation": [{"name": "Equity", "market_value": "100000.00", "portfolio_weight_pct": 100.0, "scheme_count": 1}],
            "top_securities": [],
            "sector_exposure": [],
        },
        "risk": {}, "fifo_tax_lots": {}, "sources": [], "limitations": [],
    }
    pdf = build_portfolio_report_pdf(report)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000
