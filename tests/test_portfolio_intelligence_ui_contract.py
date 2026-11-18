from pathlib import Path
import re


def test_portfolio_intelligence_page_has_all_primary_workspaces():
    html = Path("app/static/portfolio-intelligence.html").read_text()
    js = Path("app/static/portfolio-intelligence.js").read_text()
    required_ids = {
        "authPanel", "authForm", "authEmail", "authPassword", "signIn",
        "signUp", "signOut", "workspace", "portfolioSelect", "globalNotice",
        "view-overview", "view-allocation", "view-lookthrough", "view-risk",
        "view-review", "kpiValue", "qualityList", "allocationBars", "amcBars",
        "amcMetrics", "targetDimension", "targetEffectiveFrom", "targetEditor",
        "saveTargets", "driftTable", "previewContribution", "contributionResult",
        "sectorBars", "securityTable", "overlapTable", "marketCapBars",
        "riskMetrics", "reportList", "monthlyComparison", "comparisonStatus",
    }
    for element_id in required_ids:
        assert f'id="{element_id}"' in html, element_id
    for endpoint in (
        "/v1/portfolios",
        "/valuation",
        "/lookthrough",
        "/allocation",
        "/targets",
        "/allocation-drift",
        "/contribution-plan/preview",
        "/overlap-matrix",
        "/market-cap-allocation",
        "/risk?days=1095",
        "/reports",
        "/monthly-comparison",
        "/v1/reports/",
    ):
        assert endpoint in js, endpoint


def test_portfolio_intelligence_never_fabricates_unconfigured_metrics():
    html = Path("app/static/portfolio-intelligence.html").read_text()
    js = Path("app/static/portfolio-intelligence.js").read_text()
    assert "valuation_status" in js
    assert "security_concentration" in js
    assert "missing_nav_scheme_codes" in js
    assert "Verified effective-dated ISIN mappings only." in html
    assert "Simulation only" in html


def test_portfolio_intelligence_dom_references_and_event_targets_exist():
    html = Path("app/static/portfolio-intelligence.html").read_text()
    js = Path("app/static/portfolio-intelligence.js").read_text()
    ids = re.findall(r'id="([^"]+)"', html)
    assert len(ids) == len(set(ids)), "duplicate HTML ids break DOM bindings"
    references = set(re.findall(r'\$\(["\']([^"\']+)["\']\)', js))
    assert references <= set(ids), f"missing DOM ids: {sorted(references - set(ids))}"
    event_targets = set(re.findall(r'\$\(["\']([^"\']+)["\']\)\.addEventListener', js))
    assert event_targets <= set(ids), f"missing event targets: {sorted(event_targets - set(ids))}"


def test_allocation_policy_and_lookthrough_endpoints_are_wired_to_refresh():
    js = Path("app/static/portfolio-intelligence.js").read_text()
    assert "loadAllocationIntelligence(id)" in js
    assert "loadOverlapAndMarketCap(id)" in js
    assert "loadMonthlyComparison(id)" in js
    assert 'api("/v1/portfolios/"+id+"/allocation")' in js
    assert 'api("/v1/portfolios/"+id+"/overlap-matrix")' in js
    assert 'api("/v1/portfolios/"+id+"/market-cap-allocation")' in js
