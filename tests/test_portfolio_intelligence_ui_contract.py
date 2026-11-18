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


def test_lookthrough_percentage_fields_are_rendered_as_percentage_points():
    js = Path("app/static/portfolio-intelligence.js").read_text()
    # The API already returns percentage-point values (e.g. 42.5 means 42.5%).
    assert 'pct(conc.isin_identity_coverage_pct)' in js
    assert 'pct(conc.top_1_weight_of_observed_positive_pct)' in js
    assert 'pct(conc.top_5_weight_of_observed_positive_pct)' in js
    assert 'pct(conc.top_10_weight_of_observed_positive_pct)' in js
    assert 'l.security_concentration?.isin_identity_coverage_pct' in js
    assert 'l.concentration?.isin_identity_coverage_pct' not in js


def test_risk_results_are_discarded_after_portfolio_or_session_changes():
    js = Path("app/static/portfolio-intelligence.js").read_text()
    assert "riskEpoch" in js
    assert "requestedPortfolio!==portfolio" in js
    assert "requestedLoadEpoch!==loadEpoch" in js
    assert "requestedAuthEpoch!==authEpoch" in js
    assert '$("riskStatus").classList.remove("error")' in js


def test_portfolio_intelligence_renders_amc_and_classification_allocations():
    html = Path("app/static/portfolio-intelligence.html").read_text()
    js = Path("app/static/portfolio-intelligence.js").read_text()
    for element_id in ("amcBars", "amcMetrics", "categoryBars", "assetClassBars"):
        assert f'id="{element_id}"' in html
    assert 'd.amc_concentration||{}' in js
    assert 'd.category_allocation||[]' in js
    assert 'd.asset_class_allocation||[]' in js
    assert 'top_3_weight_of_observed_pct' in js


def test_monthly_review_is_loaded_and_shows_explicit_insufficient_history_state():
    html = Path("app/static/portfolio-intelligence.html").read_text()
    js = Path("app/static/portfolio-intelligence.js").read_text()
    assert 'id="monthlyReview"' in html
    assert '"/monthly-review"' in js
    assert 'INSUFFICIENT_MONTHLY_SNAPSHOTS' in js
    assert 'change_percentage_points' in js


def test_market_cap_lookthrough_is_explicitly_withheld_without_verified_security_classifications():
    html = Path("app/static/portfolio-intelligence.html").read_text()
    js = Path("app/static/portfolio-intelligence.js").read_text()
    assert 'id="marketCapStatus"' in html
    assert 'd.market_cap_allocation||{}' in js
    assert 'market_cap_allocation' in js
    assert "scheme categories are not used as a proxy" in html.lower()


def test_portfolio_wide_overlap_panel_is_loaded_and_explains_pairwise_non_additivity():
    html = Path("app/static/portfolio-intelligence.html").read_text()
    js = Path("app/static/portfolio-intelligence.js").read_text()
    assert 'id="portfolioOverlap"' in html
    assert '"/v1/portfolios/"+id+"/holdings-overlap"' in js
    assert "function renderPortfolioOverlap(data)" in js
    assert "Pairwise overlap figures are not additive" in js
    assert "isin_coverage_pct" in js
