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
| Scheme/category/sub-category/asset-class allocation | Implemented; calculation unit-tested | Decimal-safe allocation engine; scheme, segment and total-portfolio weights are distinct. API exposes scheme count, fresh-NAV coverage and unclassified value/weight by dimension. |
| AMC concentration | Implemented; calculation unit-tested | Value-weighted AMC exposure, top-1/3/5, HHI and effective AMC count. Unclassified AMC remains a visible bucket. |
| Market-cap look-through | Implemented; calculation unit-tested; live-source-unverified | Uses verified, effective-dated, source-hashed ISIN mappings. Stale, non-ISIN and unmapped exposures remain unknown. No verified live classification batch is present. |
| Fund overlap | Implemented; calculation unit-tested | Positive ISIN positions only; duplicate ISIN rows aggregated; pairwise overlap uses minimum common exposure; stale/undated disclosures withheld; portfolio duplication avoids pairwise double counting. |
| Target bands and drift | Implemented; calculation and database constraints tested | Owner-scoped, effective-dated version history; target groups reconcile to 100%; valuation freshness gates remain. |
| Contribution-only preview | Implemented; calculation tested | Preview-only; no transaction, mandate or sell writes. Advanced fund-level risk/liquidity/sector caps are not part of this report acceptance. |
| Immutable report snapshot | Implemented; API/PDF smoke-tested | JSON content hash, owner-scoped retrieval and PDF rendered from stored JSON. Snapshot now records NAV ingestion IDs, disclosure IDs and market-cap source hashes; weights use Decimal arithmetic. |
| Monthly comparison | Corrected in this execution; new unit tests added | Selects newest saved report within the final seven calendar days of each valuation month (not two arbitrary latest reports or mid-month snapshots); adds new/exited scheme flags and scheme, category, sub-category, asset-class, AMC, sector, market-cap, pairwise overlap, portfolio duplication, portfolio-value and risk deltas. AMC HHI/top-1/3/5 and NAV/holdings/classification/disclosure coverage changes are also explicit. API/CI rerun pending. |
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
- Verify month-end period semantics against actual NAV valuation dates. The comparison groups by calendar month and accepts valuation dates only in the final seven calendar days (to allow NAV publication lag); it does not claim causal attribution of market movement, contributions, withdrawals, disclosure refreshes or classification changes.
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


## Additional PDF completion work — 2026-11-18

The following work was added after the TWT monthly-comparison and snapshot-integrity changes recorded above:

- `app/reporting.py` now renders separate category, sub-category and asset-class allocation tables from the saved allocation snapshot. It preserves supplied market values and weights, including explicit unclassified rows; it does not recalculate or renormalise them.
- NAV source provenance now maps the actual snapshot fields `source_type`, `source_url`, `min_nav_date`, `max_nav_date` and `retrieved_at`. The PDF therefore shows a source label, source URL and NAV date range instead of blank source references.
- Long source references use wrapping in the PDF note style.
- Added `tests/test_reporting.py` covering allocation table rows, explicit empty states, NAV source URL/date-range mapping and PDF generation from a saved snapshot payload.

Commits for this PDF batch:
- `7f81ea1` — Complete TWT PDF allocation breakdown and source provenance.
- `d54348f` — Testable source provenance formatting for TWT report PDFs.
- `a528679` — Add regression tests for TWT report PDF allocation and provenance.

Latest observed branch head after the subsequent snapshot-integrity and tracker commits: `c3e29f716aa738203ef09d66803f5af762b3cde1`. PR #135 remained open/draft and mergeable at that check. CI run [#1994](https://github.com/yashvyas638/mf-terminal-intelligence-backend/actions/runs/44278535213) was queued when inspected; do not mark this PDF batch validated until that run completes successfully.

### Remaining PDF gates
- [ ] Confirm the new reporting tests pass on SQLite CI and the full PostgreSQL suite remains green.
- [ ] Review rendered multi-page PDF visually for table splitting, repeated headers, clipped cells, URL wrapping and footer overlap.
- [ ] Add/confirm explicit coverage numerator/denominator, retrieval timestamp and methodology-version presentation in the PDF where those values exist in the saved snapshot.
- [ ] Decide whether to include a frozen prior-month comparison appendix. If added, it must be captured into the report JSON at snapshot creation; the PDF renderer must never query current data or compute a live comparison.


## Frozen monthly comparison in report/PDF — 2026-11-18

A further TWT gap was found and addressed: the monthly comparison endpoint could compare saved reports, but the immutable report payload and PDF did not contain the prior-month comparison. This meant a PDF could not reproduce its month-on-month section later.

Changes:
- At report creation, load the portfolio owner's existing immutable snapshots and select the newest saved report for each distinct valuation month.
- Compare the current report payload with the preceding distinct valuation month before hashing/persisting the new report.
- Persist the result under `report.monthly_comparison`; the existing PDF endpoint continues to read only saved `content_json`.
- If no prior distinct month exists, persist `INSUFFICIENT_MONTHLY_SNAPSHOTS`. If the current valuation month is older than a previously saved valuation month, persist `NOT_LATEST_VALUATION_MONTH` rather than making a misleading backward comparison.
- PDF now renders the frozen portfolio value comparison, category/sub-category/asset-class/AMC/market-cap/sector movements, data coverage movement and comparison limitations.
- Added tests for monthly comparison PDF rows and an API regression test proving a generated report stores the prior-period comparison in its immutable JSON.

Commits:
- `6b479c2` — Freeze prior-month comparison into immutable TWT report snapshots.
- `c2766de` — Render frozen monthly allocation and coverage comparisons in TWT PDF.
- `3d56329` — Test frozen monthly comparison rendering in TWT PDF.
- `ecb1f57` — Verify monthly comparison is frozen into report snapshot.

Validation: latest CI must pass on the current branch head; do not reuse older CI results. Verify PDF pagination visually, particularly the additional comparison tables. A report generated before this change will not gain a monthly comparison retroactively; create a new immutable report snapshot to include the section.


## Production-readiness audit — 2026-11-18

Scope: read-only inspection of the linked Supabase project, Render workspace/service, GitHub branches/PR/CI and the existing security/backup runbook. No production deployment, migration, database write, role/ACL change, backup, restore, secret update or Auth-user creation was performed.

### Live production evidence

| Gate | Observed state | Disposition |
|---|---|---|
| Supabase project | `zgfdvhzhvccsfmpoaqah`, Singapore, ACTIVE_HEALTHY, PostgreSQL 17.11 | Connectivity healthy |
| Alembic production revision | `0028_restrictive_private_access` | Candidate migrations 0029–0031 are not applied |
| Confirmed Auth users | 1 | Two-account test blocked |
| Portfolios / distinct owners | 0 / 0 | Real cross-account isolation not demonstrated |
| Portfolio goals | 1, unlinked | Preserve existing record; no cleanup |
| Public-table RLS | Enabled on all inspected public tables | Client surface still needs full CI audit |
| Owner-scoped policies | Present for portfolios, goals, watchlist and transaction-derived reads | Policy definitions inspected; no real two-user positive/negative API test |
| Internal tables | RLS enabled, no permissive policies where intended; restrictive deny policy on designated private tables | Consistent with deny-by-default intent |
| Database roles | `anon`, `authenticated` non-login/no bypass-RLS; `service_role` bypasses RLS; privileged roles exist | Runtime connection role not verified from Render environment |
| Default ACLs | `supabase_admin` has explicit defaults granting table/sequence/function privileges to `anon` and `authenticated` | P0; candidate migration 0029 exists, production remains at 0028 |
| Supabase security advisor | 11 informational RLS-enabled/no-policy findings and leaked-password protection WARN | Do not add permissive policies to silence intentional deny-only tables; native leaked-password protection unavailable on current Free plan per runbook |
| Supabase health advisor | No findings returned | Healthy advisor result, not a full application readiness pass |
| Supabase migration API | Empty result | Alembic table is the authoritative migration ledger for this app; production revision queried directly |

### Render service and deployment evidence

- Workspace: `My Workspace`, ID `tea-dbd1ml3l550s73dendig`.
- Service: `mf-terminal-intelligence-backend`, ID `srv-dbq5gfbrjlhs73bah0l0`, Singapore, Python, Free plan, public URL `https://mf-terminal-intelligence-backend.onrender.com`.
- Render is connected to branch `audit/production-foundation`, with auto-deploy on commit enabled.
- Live service configuration still has startup command `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- The candidate branch's `render.yaml` uses a separate `MIGRATION_DATABASE_URL` and unsets it before starting Uvicorn, but that blueprint is not the configuration currently observed on the live service.
- Render deployment history shows repeated `update_failed` attempts. The latest inspected attempt was commit `bcbfeeb69ca7cc21a00933961f063b92100b57ef` and ended `update_failed`; its build completed successfully.
- Logs show the startup command invokes Alembic, and at least one process failed with `MIGRATION_DATABASE_URL must be configured separately from runtime DATABASE_URL for production schema migrations`. A separate process subsequently logged Uvicorn binding to `0.0.0.0:10000` and successful health probes, then shut down. Render later logged a port-scan timeout. Therefore the service's current active deployed SHA is **not conclusively verified** from the available deployment metadata; do not infer it from the branch head or latest failed attempt.
- Do not set environment variables, alter the start command, change service branch/plan, or trigger a deploy as part of this audit. The production configuration requires a separately provisioned migration role/URL and a non-superuser runtime role, but actual environment values and role identity must be verified privately in Render.

### GitHub / CI evidence

- Default-branch head observed: `f2c2016255abf39b2a5e88c29da80ea72970e938`.
- Portfolio Intelligence PR #135 targets `main`, is open, draft and mergeable at the inspected snapshot; latest observed PR head: `095b94188a3e777220422a504069dfd3e6a33fbf`.
- PR #135 contains migrations 0029, 0030 and 0031 plus the production audit, backup workflow and UI work. These are candidate code only; none of those migrations is applied to production.
- Latest queried CI run for the inspected PR head was run #2018 (`44278886355`), with PostgreSQL, SQLite and AMFI source validation jobs still queued at inspection time. No pass is claimed for that head.
- PR #135's latest recorded implementation comment documents older broader-suite failures (five fixture/expectation failures) and passing targeted checks; that comment is not a substitute for current-head CI.
- The tracker file is maintained on `ui/portfolio-intelligence`; it was not present on the default branch when inspected.

### Production-readiness decision

**NOT PRODUCTION READY — P0 gates remain open.**

1. Confirm Render's actual active deployment SHA and resolve the startup configuration mismatch without applying any migration automatically.
2. Privately provision and verify distinct database credentials: a non-superuser runtime role and a separately privileged migration role. Confirm effective role memberships and least-privilege grants.
3. Test migrations 0029–0031 on an isolated PostgreSQL/Supabase clone, including upgrade from revision 0028, role/default-ACL effects, constraints, and rollback/forward-fix behaviour. Migration 0029 must be reviewed carefully because it changes global function defaults for public-schema creators.
4. Configure missing GitHub Actions secrets privately, then run the read-only P0 audit and encrypted backup workflow. A dispatched or preflight-only workflow is not evidence of a backup.
5. Verify R2 upload, remote download, size and SHA-256, offline decryption/checksum, and restore to a separate isolated project.
6. Verify two real confirmed Auth accounts with one portfolio each and positive owner access plus negative cross-owner read/write tests through the deployed API. Current production counts do not support this test.
7. Verify Auth email confirmation, redirects, SMTP, signup, login, session expiry, reset and sign-out in a browser. Browser HIBP screening remains bypassable by direct Auth API callers.
8. Reconcile NAV scheduler activation and data freshness; candidate workflows are not proof of active scheduled production refresh.

### Safety record

No production SQL writes were issued. SQL used for this audit was read-only SELECT inspection. No migrations, deployments, environment updates, secret writes, user creation, portfolio creation, NAV refresh, backup, restore, or destructive operations were run. Existing portfolio-goal data was left untouched.
