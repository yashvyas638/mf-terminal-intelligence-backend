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
