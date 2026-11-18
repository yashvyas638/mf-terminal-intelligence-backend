from pathlib import Path


def test_portfolio_intelligence_page_has_all_primary_workspaces():
    html = Path("app/static/portfolio-intelligence.html").read_text()
    js = Path("app/static/portfolio-intelligence.js").read_text()
    required_ids = {
        "authPanel", "authForm", "authEmail", "authPassword", "signIn",
        "signUp", "signOut", "workspace", "portfolioSelect", "globalNotice",
        "view-overview", "view-allocation", "view-lookthrough", "view-risk",
        "view-review", "kpiValue", "qualityList", "allocationBars",
        "sectorBars", "securityTable", "riskMetrics", "reportList",
    }
    for element_id in required_ids:
        assert f'id="{element_id}"' in html, element_id
    for endpoint in (
        "/v1/portfolios",
        "/valuation",
        "/lookthrough",
        "/risk?days=1095",
        "/reports",
        "/v1/reports/",
    ):
        assert endpoint in js, endpoint


def test_portfolio_intelligence_never_fabricates_unconfigured_metrics():
    html = Path("app/static/portfolio-intelligence.html").read_text()
    js = Path("app/static/portfolio-intelligence.js").read_text()
    assert "Not configured" in html
    assert "not yet configured" in html
    assert "valuation_status" in js
    assert "security_concentration" in js
    assert "missing_nav_scheme_codes" in js
