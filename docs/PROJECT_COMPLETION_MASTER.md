# MF Terminal — Project Completion Master

Last audited: 2026-11-18  
Scope of this execution: **TWT Mutual Fund Allocation Report — October 2026**  
Working branch: `ui/portfolio-intelligence`  
Pull request: [#135](https://github.com/yashvyas638/mf-terminal-intelligence-backend/pull/135)  
Release boundary: isolated branch only; no merge, production migration, production data write, or Render deployment.

## Tracker recovery note

The requested path `docs/PROJECT_COMPLETION_MASTER.md` did not exist in the inspected branch tree at the start of this execution. The repository contained `docs/PRODUCT_DELIVERY_CHECKLIST.md`, `docs/PORTFOLIO_INTELLIGENCE_IMPLEMENTATION.md`, and the TWT specification. This file is being established as the requested TWT-specific completion tracker; it does not replace the broader product delivery checklist.

## TWT acceptance register

| Workstream | Current status | Evidence / remaining gate |
|---|---|---|
| Scheme/category/sub-category/asset-class allocation | Implemented; calculation unit-tested | Decimal-safe allocation engine; scheme, segment and total-portfolio weights are distinct. API and snapshot integration are present. |
| AMC concentration | Implemented; calculation unit-tested | Value-weighted AMC exposure, top-1/3/5, HHI and effective AMC count. Unclassified AMC remains a visible bucket. |
| Market-cap look-through | Implemented; calculation unit-tested; live-source-unverified | Uses verified, effective-dated, source-hashed ISIN mappings. Stale, non-ISIN and unmapped exposures remain unknown. No verified live classification batch is present. |
| Fund overlap | Implemented; calculation unit-tested | Positive ISIN positions only; duplicate ISIN rows aggregated; pairwise overlap uses minimum common exposure; stale/undated disclosures withheld; portfolio duplication avoids pairwise double counting. |
| Target bands and drift | Implemented; calculation and database constraints tested | Owner-scoped, effective-dated version history; target groups reconcile to 100%; valuation freshness gates remain. |
| Contribution-only preview | Implemented; calculation tested | Preview-only; no transaction, mandate or sell writes. Advanced fund-level risk/liquidity/sector caps are not part of this report acceptance. |
| Immutable report snapshot | Implemented; API/PDF smoke-tested | JSON content hash, owner-scoped retrieval and PDF rendered from stored JSON. Snapshot now records NAV ingestion IDs, disclosure IDs and market-cap source hashes; weights use Decimal arithmetic. |
| Monthly comparison | Corrected in this execution; new unit tests added | Selects newest saved report for each distinct valuation month (not two arbitrary latest reports); adds scheme, category, sub-category, asset-class, AMC, sector, market-cap, portfolio-value, duplication and risk deltas. INR and percentage-point changes are explicit. API/CI rerun pending. |
| API ownership and safety | Partially verified; one actual gap fixed | Market-cap endpoint now checks portfolio ownership before valuation reads. A regression test was added. Existing overlap route has the same ordering guard. Full two-user route matrix remains a release gate. |
| PDF/export | Implemented; existing API test checks PDF signature | Export reads the immutable saved snapshot; browser download and visual review remain unverified. |
| Live data coverage | Not verified | No production holdings disclosure or verified market-cap classification batch was imported by this work. Unknown exposure must remain visible. |

## Changes made in this execution

1. Added `app/twt_monthly_report.py` for immutable monthly-period selection and report-to-report comparison.
2. Updated `GET /v1/portfolios/{portfolio_id}/monthly-comparison` to compare the newest saved report from each of the two latest distinct valuation months.
3. Added INR and percentage-point deltas for scheme, category, sub-category, asset-class, AMC, sector and market-cap rows.
4. Added portfolio-value, portfolio-duplication and risk-metric changes, with explicit withheld states when evidence is not comparable.
5. Fixed market-cap API ownership ordering so authorization is checked before portfolio valuation.
6. Changed snapshot holding-weight calculation to Decimal arithmetic.
7. Added immutable input references to saved reports: NAV ingestion snapshot IDs, holdings disclosure IDs and market-cap source hashes.
8. Added `tests/test_twt_monthly_report.py` and a market-cap ownership-order regression test in `tests/test_api.py`.

## Test and release evidence

- Existing PR #135 CI at the previously observed head passed SQLite and PostgreSQL jobs; that result predates the changes listed above and is **not** evidence for the current head.
- New targeted tests are committed but must pass on the latest branch head.
- Required next checks: full SQLite suite, PostgreSQL suite, Ruff, JavaScript syntax/UI contract checks, migration tests, and PR status checks.
- Review report snapshot immutability by refreshing NAV/holdings inputs after snapshot creation and verifying the stored JSON/hash/PDF remain unchanged.
- Verify monthly comparison API with at least three snapshots where two are in the same valuation month; verify it selects the latest report for that month and the latest report from the preceding distinct month.
- Verify month-end period semantics against actual NAV valuation dates. The comparison groups by calendar month of the saved valuation date; it does not claim causal attribution of market movement, contributions, withdrawals, disclosure refreshes or classification changes.
- Verify a live official holdings disclosure and an independently sourced market-cap classification artifact before publishing verified look-through figures.

## Explicit non-goals

- No UI polish, redesign, visual refresh or duplicate dashboard.
- No Smart SIP expansion or automated contribution execution.
- No recommendation to buy, sell, switch or copy another investor's portfolio.
- No production database migration, production data import, secret change, deployment or PR merge.

## Definition of done

TWT is ready for code review only when all of the following are true:

1. Calculation and API tests pass on SQLite and PostgreSQL for the current exact commit.
2. Allocation, market-cap, overlap and AMC outputs reconcile and preserve unknown/partial coverage.
3. Monthly comparison selects distinct valuation months and reports both INR and percentage-point movement without inventing missing metrics.
4. A saved report remains byte-for-byte stable after later NAV/disclosure/classification refreshes; PDF is rendered from that saved report.
5. API ownership checks precede private portfolio reads and cross-owner access is denied.
6. Migration and CI evidence are attached to PR #135.
7. Live holdings/classification coverage is either independently verified or prominently marked partial/unavailable.
8. Release remains blocked pending explicit review and approval; this task does not authorize merge or deployment.
