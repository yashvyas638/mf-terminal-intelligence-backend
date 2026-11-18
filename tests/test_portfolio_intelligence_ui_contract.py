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
        "smartSipBenchmark", "smartSipDimension", "smartSipBudgetApproved",
        "runSmartSip", "smartSipResult", "smartSipStatus",
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
        "/benchmarks/tri-options",
        "/smart-sip/preview",
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
    assert 'target_drift:"Target drift · pp"' in js
    assert 'api("/v1/portfolios/"+id+"/allocation")' in js
    assert 'api("/v1/portfolios/"+id+"/overlap-matrix")' in js
    assert 'api("/v1/portfolios/"+id+"/market-cap-allocation")' in js



def test_monthly_snapshots_and_pdf_include_twt_allocation_intelligence():
    main = Path("app/main.py").read_text()
    reporting = Path("app/reporting.py").read_text()
    js = Path("app/static/portfolio-intelligence.js").read_text()
    for field in (
        '"allocation_intelligence": allocation_intelligence',
        '"overlap_intelligence": overlap_intelligence',
        '"market_cap_intelligence": market_cap_intelligence',
        '"target_policy_snapshot": target_policy_snapshot',
        '"target_drift_snapshot": target_drift_snapshot',
        '"snapshot_consistency": {',
        '"/v1/portfolios/{portfolio_id}/monthly-comparison"',
        '"WITHHELD_OR_PARTIAL_DISCLOSURE_COVERAGE"',
    ):
        assert field in main, field
    for heading in (
        "Allocation and AMC concentration",
        "Fund overlap and duplicated exposure",
        "Underlying market-cap allocation",
        "Target policy and allocation drift",
        "Snapshot consistency:",
    ):
        assert heading in reporting, heading
    assert "weight_of_total_portfolio_pct" in js


def test_monthly_comparison_renderer_consumes_nested_metric_contract():
    js = Path("app/static/portfolio-intelligence.js").read_text()
    assert "row.metrics||{}" in js
    assert "change_percentage_points" in js
    assert "previous_inr" in js
    assert "sub_category" in js
    assert "overlap_pairs" in js
    assert "data_coverage" in js


def test_allocation_target_versions_support_same_day_revisions():
    main = Path("app/main.py").read_text()
    db = Path("app/db.py").read_text()
    migration = Path("migrations/versions/0030_portfolio_allocation_targets.py").read_text()
    assert "next_version = int(latest_version) + 1" in main
    assert "desc(PortfolioAllocationTarget.version)" in main
    assert "version: Mapped[int]" in db
    assert '"effective_from", "version"' in migration

def test_portfolio_intelligence_cache_keys_and_lookthrough_diagnosis_match_api_contract():
    html = Path("app/static/portfolio-intelligence.html").read_text()
    js = Path("app/static/portfolio-intelligence.js").read_text()

    assert 'portfolio-intelligence.css?v=3' in html
    assert 'portfolio-intelligence.js?v=3' in html
    assert 'l.security_concentration?.isin_identity_coverage_pct' in js
    assert 'l.concentration?.isin_identity_coverage_pct' not in js
