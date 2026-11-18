# MF Terminal — Project Completion Master

Last audited: 2026-11-18  
Scope of this execution: **TWT Mutual Fund Allocation Report — October 2026, plus Smart SIP and contribution-routing backend hardening**  
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
- No automated contribution execution. Smart SIP remains an evidence-gated, non-executing preview; this follow-up adds backend budget/routing guardrails only.
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


### Follow-up evidence — Render startup root cause and moving PR head (2026-11-18)

- A second timestamped Render log inspection confirms the startup failure is deterministic on the affected instances: `MIGRATION_DATABASE_URL must be configured separately from runtime DATABASE_URL for production schema migrations`. The live Render start command invokes Alembic before Uvicorn, while the Render service's environment/configuration has not been proven to provide the required separate migration URL. Some process logs show Uvicorn did start and answer health probes, but other attempts exited before binding and Render subsequently reported a port-scan timeout. This is a configuration/credential provisioning blocker, not a build dependency failure.
- The live service is configured for automatic deploys from `audit/production-foundation`. No Render environment or service settings were changed because this is production infrastructure and the required secret values are not available for safe configuration.
- After the audit tracker commit, the PR branch continued receiving parallel commits. Latest subsequently observed PR #135 head: `2539941757fda3a38f5fbc790bbdd54f38b4b5d8`. CI run `44279169927` (CI) was still queued with PostgreSQL, SQLite and AMFI source-validation jobs queued. Do not mark current-head tests passed.
- Audit evidence commit: `b8434b896ac91d16535b396d574f1eb6295c6724`. This commit adds the production-readiness audit section to this master tracker.


## Month-end eligibility and comparison deduplication — 2026-11-18

A branch audit found that the snapshot creation path had two overlapping monthly-comparison blocks after parallel edits. The later block overwrote the earlier result. This was consolidated into one owner-scoped prior-snapshot query and one comparison decision.

- Month-end comparison eligibility is now explicit and shared through `is_month_end_valuation_date`: only valuation dates in the final seven calendar days of the month qualify.
- `select_latest_distinct_months` excludes mid-month snapshots, so the monthly API cannot accidentally compare arbitrary mid-month reports.
- Snapshot creation distinguishes `CURRENT_REPORT_NOT_MONTH_END`, `INSUFFICIENT_MONTHLY_SNAPSHOTS`, and `NOT_LATEST_VALUATION_MONTH`; it only freezes a comparison when the current report is an eligible month-end snapshot and a prior distinct month exists.
- API regression fixture now uses two distinct month-end dates; boundary tests cover month-end, seven days before month-end, eight days before month-end and invalid dates.
- Duplicate snapshot query/overwrite logic removed from `app/main.py`.

Commits:
- `d1d571f` — Consolidate frozen TWT comparison and enforce month-end eligibility.
- `43ef2c7` — Test immutable TWT comparison using month-end valuation snapshots.
- `aa78bfa` — Expose shared month-end eligibility rule for TWT snapshots.
- `544933c` — Test month-end eligibility boundaries for TWT comparisons.

Latest observed PR head for this batch: `544933cd19829e2b0951bf724756d2281e48af80`. CI run [#2064](https://github.com/yashvyas638/mf-terminal-intelligence-backend/actions/runs/44279404527) was queued when checked; current-head tests are not yet marked passed.


## Consecutive-month comparison guard — 2026-11-18

A further edge case was identified: selecting the two latest available month-end snapshots could compare October directly with December when November had no eligible snapshot, incorrectly presenting a two-month movement as month-on-month.

- `select_latest_distinct_months` now returns only the latest month when the immediately preceding calendar month is missing.
- The monthly comparison API and report snapshot therefore withhold the comparison instead of silently spanning a gap.
- Added a regression test for December/October snapshots with November missing.

Commits:
- `8478833` — Withhold month-on-month comparison when a valuation month is missing.
- `22092c1` — Test missing month gap withholding for TWT comparison.

The latest observed CI run before these commits was [#2076](https://github.com/yashvyas638/mf-terminal-intelligence-backend/actions/runs/44279549073), queued against a later branch head. Recheck CI against the exact current PR head before marking this change validated.


## Snapshot integrity gate for monthly comparisons — 2026-11-18

- Added `decode_verified_snapshot` to verify SHA-256 before parsing saved report JSON.
- Report creation now withholds the frozen monthly comparison if any previous owner-scoped snapshot fails integrity verification; it does not silently skip a corrupted latest snapshot and compare against an older month.
- The monthly comparison API likewise returns `SNAPSHOT_INTEGRITY_FAILURE` and the affected snapshot IDs instead of using unverified JSON.
- Added unit coverage for valid hashes, mismatched hashes and malformed JSON.

Commits:
- `17fd08b` — Verify immutable report hashes before monthly comparisons.
- `6838842` — Withhold frozen comparison when prior report snapshot hash fails.
- `14f4b52` — Verify snapshot SHA-256 before serving monthly comparison.
- `e1433bb` — Test SHA-256 validation before TWT snapshot comparison.
- `8e8f4e4` — Keep TWT monthly test imports lint compliant.

Validation remains pending for the latest exact branch head. CI must pass SQLite, PostgreSQL, lint and the AMFI read-only validation jobs.


## Smart SIP, contribution routing and database integrity follow-up — 2026-11-18

**Scope:** backend only. Reuse the existing Smart SIP engine, target policy, contribution preview and API routes. No duplicate engine, UI redesign, production migration, deployment or transaction execution.

### Changes committed to `ui/portfolio-intelligence`

- Allocation target ownership is now enforced by a composite database foreign key from `(portfolio_id, owner_user_id)` to the matching portfolio identity. Migration `0032_target_owner_fk` preflights existing rows and aborts on missing parents or owner mismatches before adding the constraint.
- Contribution preview accepts an optional explicit total contribution ceiling (`max_contribution_inr`) and a per-bucket post-weight ceiling (`max_post_weight_pct`). Requests exceeding the approved total ceiling fail with HTTP 422; the weight ceiling can only tighten the saved target.
- Any unallocated contribution is now represented explicitly as `__UNALLOCATED_CASH__` in the post-contribution allocation so the displayed weights reconcile to 100% instead of silently omitting cash.
- Smart SIP approval now requires both the approval flag and a positive INR amount. A bare approval boolean is not treated as a usable additional-contribution budget.
- Added calculation tests for risk ceilings, over-budget rejection and unallocated-cash reconciliation; database tests for mismatched portfolio ownership; API tests for contribution caps/no transaction writes and Smart SIP budget approval.

### Commits in this follow-up

- `8baed9f` — Enforce portfolio target owner consistency in the ORM model.
- `690ca9c` — Add composite owner foreign-key migration `0032_target_owner_fk`.
- `5db7122` — Test database rejection of mismatched target ownership.
- `b54a4d4` — Add contribution budget/weight ceilings and cash reconciliation.
- `bc98de3` — Expose contribution risk caps and require a Smart SIP INR budget.
- `99d28eb` — Test contribution risk caps and cash reconciliation.
- `d3dfd4f` — Test Smart SIP explicit budget approval.
- `be3aacb` — Add contribution API tests for risk caps and preview-only behaviour.

### Validation status and remaining constraints

- [ ] Full SQLite CI on the exact latest PR head.
- [ ] Full PostgreSQL CI including migration 0032 on the exact latest PR head.
- [ ] Confirm the database mismatch-owner regression fails without the new composite FK and passes with migration 0032.
- [ ] Confirm the contribution API test returns HTTP 422 above the approved cap and never writes a transaction.
- [ ] Review migration 0032 against a PostgreSQL database with existing allocation target rows; production remains read-only until separately approved.
- [ ] Add cross-dimension routing constraints before describing the planner as a full fund-level optimiser. The current preview evaluates one saved dimension at a time; it does not combine AMC, scheme, sector, security, liquidity or tax constraints across dimensions.
- [ ] Wire the new INR budget input into the UI in a separate UI task. Until then, a boolean-only Smart SIP approval intentionally remains ineligible for an additional top-up.
- [ ] Review rounding-boundary cases where a very small target deficit is below one paisa; the contribution planner must never exceed the configured cap because of residual rounding.

**Current disposition:** implementation and regression tests committed; CI was queued at the latest observed head and is not yet a pass. Smart SIP remains preview-only, and no buy order, SIP mandate, portfolio transaction or cash movement is created.


### Rounding and risk-ceiling hardening — 2026-11-18

A boundary review found that half-up rounding could allocate one paisa more than a bucket's fractional target deficit. This could breach a tight saved/risk target by a paisa.

- Contribution amounts and explicit INR ceilings now reject fractions of a paisa.
- Bucket allocations are rounded down first; remaining whole paise are distributed by largest fractional remainder only when the bucket still has at least one paisa of target capacity.
- Residual paise that cannot be routed safely remain in the explicit unallocated-cash row.
- Added regressions for a sub-paisa target deficit and fractional-paisa request rejection.

Additional commits:
- `0d1c511` — Prevent paise rounding from breaching contribution target caps.
- `f5a0495` — Test sub-paisa deficit and fractional-paisa handling.

Latest observed branch head: `f5a04951cce7b7b8db5e8e46edc7a8b92c5120fe`. CI runs for this exact head were queued when checked; no pass is claimed yet.


## TWT allocation report and PDF finalisation pass — 2026-11-18

- PDF allocation evidence now includes the unclassified market value/weight and fresh-NAV coverage alongside scheme count.
- AMC summary includes top-1/top-3/top-5 concentration, HHI and effective AMC count.
- Pairwise overlap appendix now shows both funds' disclosure dates, coverage percentages and matched ISIN exposure amounts; the main pair table retains overlap value, common-ISIN count and per-fund overlap ratios.
- Frozen monthly PDF tables now include scheme presence (new/continuing/exited), scheme/category/sub-category/asset-class/AMC/sector/market-cap movements, pairwise overlap movement, portfolio duplication and data-coverage movement.
- Snapshot source provenance binds NAV ingestion snapshot IDs to the exact NAV observation dates used in the valuation, rather than looking up a potentially newer observation after report calculation.
- Monthly comparison API verifies stored SHA-256 hashes before parsing/comparing snapshots and withholds on integrity failure.
- Monthly comparison is withheld across missing calendar months; December versus October is not labelled as one-month movement.
- API integration coverage creates September/October month-end snapshots, checks the frozen comparison in report JSON, exercises the monthly comparison endpoint, changes NAV after snapshot creation and confirms the saved report remains stable.
- PDF regression tests were aligned to the explicit presence-status column.

Commits in this pass include:
- 30ae695 — Include fund-level overlap coverage and matched exposure in TWT PDF.
- dcd764c — Show unclassified allocation and NAV coverage in TWT PDF.
- 685c8f2 — Bind NAV source IDs to the exact observation date frozen in report valuation.
- 14f4b52 — Verify snapshot SHA-256 before serving monthly comparison.
- e1433bb — Test SHA-256 validation before TWT snapshot comparison.
- 0d5d4bf — Exercise TWT monthly-comparison API against frozen month-end snapshots.
- fbe50de — Align PDF monthly comparison tests with presence-status column.

**Validation status:** source and test changes are committed; current-head CI remains queued at the last inspection. Do not mark SQLite, PostgreSQL, lint or PDF pagination as passed until the current PR head's workflow completes. Visual PDF pagination review and independent live holdings/classification-source verification remain open.


## TWT PDF risk and coverage completion — 2026-11-18

- PDF now prints disclosure coverage in rupees and percentage terms, with fresh/stale covered values and counts of missing/stale disclosure and NAV schemes.
- NAV freshness prints fresh active schemes / total active schemes, coverage percentage and maximum allowed NAV age.
- Market-cap section prints classified and unclassified INR exposure, positive look-through denominator, classification coverage and reconciliation difference/status.
- Monthly comparison PDF includes scheme/category/sub-category/asset-class/AMC/market-cap/sector and pairwise overlap movement, AMC concentration metrics, duplicated exposure, data coverage movement and historical risk changes.
- Added a monthly-comparison risk movement table to the PDF.

Commits:
- `36f1dfd` — Expose NAV and holdings coverage numerators in TWT PDF.
- `31fb3b1` — Render month-on-month historical risk deltas in TWT PDF.

Current validation: CI runs on the branch have been queued in GitHub Actions; the exact latest head must be checked before marking this complete. Visual PDF pagination review remains outstanding.


### Display-weight rounding reconciliation — 2026-11-18

- The post-contribution allocation now reconciles its four-decimal displayed weights to exactly 100.0000%.
- Any display-only rounding residual is assigned to the explicit unallocated-cash row when present, rather than increasing a fund bucket's displayed risk weight.
- Commit: `1c1dbcb` — Reconcile displayed contribution weights to exactly 100 percent.
- Latest implementation head at this update: `1c1dbcb997b1c9bd3170b82ee9d7aa8d341b59d1`; CI remains pending.


### Infeasible risk-policy handling — 2026-11-18

- Contribution preview now rejects a requested post-weight ceiling below any saved bucket minimum instead of silently weakening the saved minimum constraint.
- Added a regression test for the infeasible risk-policy case.
- Commits: `0be261e` (reject conflicting ceiling/minimum policy), `ee1d583` (test infeasible risk-policy rejection).
- CI for the exact current head remains pending.


## Monthly comparison UI contract fix — 2026-11-18

The frontend monthly comparison renderer was still reading the previous flat API shape (`previous_value`, `current_value`, `change`) while the current backend returns nested metric objects (`row.metrics`, `previous`, `current`, `change_inr`, `change_percentage_points`). This would have rendered blank or misleading monthly comparison rows despite correct backend calculations.

- Reworked `renderMonthlyComparison` to consume nested metric objects and show INR deltas separately from percentage-point deltas.
- Added scheme, sub-category and pairwise overlap sections; added portfolio value, duplication, AMC concentration, data coverage and risk summaries.
- Added DOM contract regression assertions for the nested monthly comparison response shape.
- Restored the exact allocation heading string expected by the existing PDF contract test.

Commits:
- `d129d53` — Render nested TWT monthly comparison metrics correctly in UI.
- `b50a4d4` — Preserve TWT PDF section heading contract.
- `ae21eb0` — Guard TWT monthly comparison UI against API metric shape drift.

Current head validation is pending. CI must pass JavaScript validation, UI contract tests, PDF tests, SQLite and PostgreSQL suites.
