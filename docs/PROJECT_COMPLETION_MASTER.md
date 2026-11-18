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


## Final TWT PDF methodology presentation — 2026-11-18

- PDF now renders the frozen methodology dictionary (valuation, risk, capital gains, allocation, overlap, market-cap and snapshot methodology/version) as a separate table before limitations.
- The frontend monthly renderer was also updated to retain the target-drift label contract while using nested API metrics.

Commits:
- `dd70f9b` — Render methodology versions and methods in TWT PDF.
- `e84ca82` — Preserve target drift monthly comparison UI contract.

Visual pagination and CI remain pending.


## TWT immutable snapshot read-integrity gate — 2026-11-18

A final API-path audit found that monthly comparison already verified snapshot SHA-256 before parsing, but the individual report-detail and PDF endpoints still parsed `content_json` directly. A corrupted snapshot could therefore be returned as trusted financial data or rendered to PDF even though the monthly comparison correctly withheld it.

- `GET /v1/reports/{report_id}` now verifies the stored SHA-256 and JSON object before returning the report. Invalid or malformed snapshots return HTTP 409 and are not served.
- `GET /v1/reports/{report_id}/pdf` applies the same integrity gate before rendering. The PDF is generated only from a verified immutable snapshot.
- Added an API regression to corrupt the stored payload while retaining its original digest and assert that both detail and PDF endpoints return HTTP 409.

Commits:
- `c178572` — Fail closed on corrupted TWT report snapshots.
- `1a8f888` — Test corrupted TWT snapshots are withheld from reads and PDFs.

**Validation status:** code and regression test are committed. CI has not yet been checked on the exact new head; do not mark tests passed until the branch workflow completes. No production data, migrations, deployment or UI styling were changed.


## TWT month-end boundary correction — 2026-11-18

A further audit found an off-by-one issue in the month-end eligibility helper. The code treated a seven-day window as a date difference of 0 through 7 inclusive, which admits eight calendar dates (for a 31-day month, October 24–31). The report specification requires exactly the final seven calendar dates.

- Corrected the helper to accept date differences from 0 through 6 for the default seven-calendar-day window.
- Rejects invalid zero/negative window sizes.
- Expanded boundary tests for 31-day, 30-day and leap-year February month ends. October 25 is now the first eligible date; October 24 is rejected.

Commits:
- `8afba58` — Correct TWT month-end seven-calendar-day boundary.
- `5130001` — Test exact seven-calendar-day TWT month-end window.

**Validation:** targeted regression is committed; current-head CI is pending. The previous CI run was queued on the prior head and cannot validate these commits. Do not claim the suite passed until the new run completes.


## Production blocker recheck — exact live state at PR head 48af23c — 2026-11-18

This is a fresh recheck against the current branch and linked Render service, not a carry-forward of the older SHA in the previous audit section.

### Exact GitHub state

- PR #135 remains open and draft, targeting `main`.
- Exact branch / PR head at this check: `48af23c2044c089644f1476a7f606deeef354764` (commit: “Record TWT snapshot read-integrity fix in master tracker”).
- CI run [#2142](https://github.com/yashvyas638/mf-terminal-intelligence-backend/actions/runs/44280450400) is associated with this exact head. Its three jobs — SQLite, PostgreSQL and live read-only AMFI validation — were all `queued` at inspection. No tests are claimed as passed for this head.
- Candidate `render.yaml` on this branch declares both `DATABASE_URL` and `MIGRATION_DATABASE_URL` as separately supplied secrets and starts with Alembic before Uvicorn. `migrations/env.py` calls `migration_database_url()` before running either online or offline migrations. Production intentionally fails closed when the migration URL is absent or equal to the runtime URL.

### Fresh Render configuration and failure evidence

- The actual Render service remains connected to `audit/production-foundation`, not this PR branch, with auto-deploy enabled.
- The live service's configured start command is still `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`. This differs from the candidate `render.yaml` command, which unsets the migration URL after Alembic and before Uvicorn.
- Latest listed Render deploy remains `update_failed` for commit `bcbfeeb69ca7cc21a00933961f063b92100b57ef`; Render reports the build succeeded and the deploy process exited non-zero.
- Fresh timestamped application logs from 2026-11-18 08:17–08:18 UTC show the live start command invoking Alembic, then `app/db.py:migration_database_url()` raising exactly: `MIGRATION_DATABASE_URL must be configured separately from runtime DATABASE_URL for production schema migrations`. Render then reports no open ports / port-scan timeout. This proves the currently observed deploy failure is caused by the missing separate migration credential in the live service configuration, not by pip/build failure.
- Render's service metadata does not expose secret values, and no attempt was made to read or change them. A valid fix requires the owner to provision a dedicated migration connection string, verify that it is different from the runtime URL, and verify the database role has only the required migration privileges. Do not copy the service-role key or a superuser URL into the runtime `DATABASE_URL`.
- The app's guard is correct and must remain fail-closed. Do not weaken it, fall back to the runtime role, bypass Alembic, or start the app against a schema that may be behind the code.

### Safe remediation plan (owner action required)

1. In Supabase, provision/identify a dedicated migration database role and connection string. Keep the runtime role non-owner/non-superuser and least-privileged. Store the migration URL as a separate Render secret named `MIGRATION_DATABASE_URL`; do not paste credentials into GitHub, issues, chat or source files.
2. Verify privately that the two URLs are different and that the migration role can apply the pending Alembic chain. Confirm the runtime role cannot perform DDL or bypass RLS.
3. Before production migration, finish isolated PostgreSQL migration tests through revision `0032_target_owner_fk`, review the P0 default-ACL migration, and confirm a verified encrypted backup plus isolated restore.
4. Reconcile the live Render start command with the reviewed repository blueprint. Preserve the required sequence: migrations complete successfully using the migration role; remove the migration credential from the application process; then start Uvicorn on Render's `$PORT`.
5. Only after explicit release approval, apply migrations/deploy and verify the full deployed SHA via the health endpoint. Do not infer the active SHA from Git branch head or a failed deploy attempt.

### Work completed in this recheck

- Re-read the current PR head, branch tree, `render.yaml`, Alembic environment, migration-URL guard/tests, CI workflow, latest CI run/jobs, Render service metadata, deploy history, events and timestamped application logs.
- Confirmed the repository already contains the correct fail-closed migration credential guard and a candidate Render blueprint that separates migration and runtime credentials. The production service has not adopted that configuration and has not been given a verified migration secret.
- No source-code bypass was introduced because it would weaken production database security and could leave the application running against an incompatible schema.
- No Render setting, secret, branch, start command or deployment was changed. No Supabase SQL write, migration, backup/restore, Auth-user creation or production data change was performed.

**Disposition: production remains blocked by missing owner-provisioned migration credentials, P0 database ACL migration, backup/restore evidence and two-account isolation.** The failure is now tied to timestamped Render logs and the exact live service configuration.

### TWT overlap-pair identity hardening — 2026-11-18

A month-on-month comparison audit found that pair identity was built from the incoming `scheme_a:scheme_b` order. If an overlap provider returned the same two schemes in reverse order in a later snapshot, the report could falsely mark the pair as exited and new, and directional overlap percentages could be assigned to the wrong scheme.

- Monthly comparison now canonicalises each pair by scheme code before matching.
- When canonicalisation reverses the source order, the two fund-NAV denominator percentages are swapped with their corresponding schemes.
- Invalid self-pairs, missing scheme identifiers and duplicate canonical pairs withhold the overlap-pair section rather than silently collapsing rows.
- Added regression coverage for reversed pair order, continuing-pair identity, INR delta and both directional denominator values.

Commits:
- `c05cc29` — Normalize fund pair identity in monthly TWT comparisons.
- `4adef94` — Test order-independent TWT fund overlap comparisons.

Validation: changes are committed on `ui/portfolio-intelligence`; run CI against the latest branch head before treating the regression as passed. PDF pagination/browser rendering review remains open. No merge, deployment or production data changes.


## TWT stale-disclosure duplication correction — 2026-11-18

The overlap engine correctly withheld pairwise overlap values when either disclosure was stale, but the portfolio-wide duplicated-exposure aggregation still included stale fund holdings. That contradicted the methodology limitation stating stale disclosures are excluded and could inflate duplication totals.

- Stale disclosures remain available for pair diagnostics (pair values are withheld and status explains why).
- Only fresh disclosures now contribute to portfolio-wide gross positive look-through exposure and duplicated-exposure calculations.
- Added a regression where one of two funds has a stale disclosure: the fresh fund's exposure remains in the denominator, stale exposure is excluded, and duplicated exposure is zero.

Commits:
- `bc962c5` — Exclude stale disclosures from portfolio duplication totals.
- `e49d611` — Test stale holdings cannot inflate TWT duplication metrics.

**Validation:** committed; awaiting current-head CI. The result remains a source-limited observed exposure, not a claim that missing/stale disclosures have zero overlap.


## Smart SIP valuation freshness gate — 2026-11-18

A focused API-path audit found that Smart SIP treated portfolio need as verified when the drift response was available and its valuation date matched, even if the underlying portfolio valuation was marked stale or incomplete. This could expose an underweight label from stale valuation evidence (the independent top-up gate still prevented execution, but the evidence label itself was too permissive).

- Portfolio need is now verified only when valuation status is COMPLETE, freshness is FRESH, and the drift valuation date matches the same valuation date.
- Stale, incomplete, missing-date or mismatched-date valuation evidence returns portfolio need status WITHHELD and no underweight bucket list.
- Added API regression coverage for stale valuation fail-closed behaviour.
- Commits: `9725451` (fresh complete valuation gate), `18fc080` (stale valuation regression).

**Validation:** committed to `ui/portfolio-intelligence`; CI for the exact latest head has not yet been observed. The previously observed run #44280273558 is for an older commit and remains queued; it is not valid evidence for this change. PR #135 currently reports mergeable=false, so merge readiness is also unresolved. No merge, deployment or production migration was performed.


### Latest branch/PR state correction — 2026-11-18

After the Smart SIP freshness fix and tracker update, GitHub reports PR #135 mergeable=true against `main` (0 commits behind; branch contains 881 commits ahead). This supersedes the transient mergeable=false state recorded in the previous section. The current head is `cedf292a90253b9c127cbafb2c619e2a4a6cf520`. No combined status checks are currently attached to that exact SHA, and the older queued run is not a substitute. CI evidence remains pending.

### TWT monthly PDF overlap denominator completeness — 2026-11-18

The PDF monthly comparison table showed only Fund A's overlap ratio movement. Fund A and Fund B use different NAV denominators, so both percentage-point movements are required to interpret a pair correctly.

- Extended the monthly PDF row builder to support a second directional percentage-point metric.
- The pairwise overlap movement table now prints both Fund A and Fund B ratio changes in separate columns, with a narrower table layout to remain within the A4 content width.
- Added a regression test for both directional deltas and column alignment.

Commits:
- `7af702a` — Show both fund overlap ratios in monthly TWT PDF.
- `ca8b510` — Test both directional overlap deltas in TWT PDF.

Validation remains pending on the latest branch head; no test pass is claimed until CI completes. Visual PDF pagination review remains open.


### TWT execution checkpoint — latest observed PR head

- Latest PR #135 head verified: `1c6741446a9b0aa510fd0746d1346dd0e6fe4393` (draft, open, mergeable=true).
- This head includes the exact seven-calendar-day month-end boundary correction, snapshot detail/PDF SHA-256 fail-closed checks, stale-disclosure exclusion from portfolio duplication totals, canonical pair identity comparison, and both directional overlap-ratio PDF deltas.
- Latest observed CI run: [#2175](https://github.com/yashvyas638/mf-terminal-intelligence-backend/actions/runs/44281293794). SQLite, PostgreSQL and AMFI validation jobs are still **queued**; no test pass is claimed. Combined commit status currently has no completed status checks.
- Visual multi-page PDF review and live source-coverage verification remain open. PR is not approved, merged or deployed. No production database or Render changes were made.

Directional overlap PDF labels were clarified to `Change pp A` and `Change pp B`, matching the canonical fund ordering used by the comparison engine. Regression assertion updated accordingly.

- `ec7decb` — Label both directional fund overlap deltas.
- `7b0e371` — Assert labelled fund A and B overlap deltas.

### TWT historical-risk comparison comparability gate — 2026-11-18

A report comparison audit found that historical-risk deltas were calculated without checking whether both snapshots used the same lookback window or whether either risk calculation was flagged stale/invalid. Numerically populated values alone do not make the comparison valid.

- Risk deltas now require identical, positive `lookback_days` in both immutable reports.
- Both report-level risk statuses must be `OK`; stale NAV or other non-OK input states withhold risk movement.
- Withheld metrics expose no previous/current/change numbers and include an explicit reason status.
- Added regressions for different lookback windows and stale-NAV risk inputs.

Commits:
- `b3978a4` — Withhold TWT risk deltas across incompatible inputs.
- `42b194b` — Test comparable risk windows for TWT monthly reports.

Validation remains pending on the exact latest PR head. No merge, deployment or production data changes.


### Smart SIP budget precision hardening — 2026-11-18

- The Smart SIP preview request now rejects additional-contribution budgets with fractional paise (more than two decimal places), matching the INR contribution planner's money precision contract.
- Added API regression coverage for a ₹5,000.001 budget returning HTTP 422.
- Commits: `8a162f6` (validation), `9094535` (regression test).
- The Smart SIP portfolio-need gate also requires a COMPLETE, FRESH valuation and exact date match; stale/incomplete valuation exposes no underweight buckets.
- **Validation remains pending:** GitHub Actions run #2175 is still queued for its three jobs at last inspection. The latest branch head after this hardening must be rechecked for its own CI run. No tests are marked passed based on the older queued run.


### Latest Smart SIP delivery checkpoint — 2026-11-18

- Latest PR #135 head after all current Smart SIP fixes: `4ae6296ad5094e9260740351515b41484d7a191d`.
- PR state: open, draft, unmerged; GitHub currently reports mergeable=true against `main`.
- Added paise-precision validation for `additional_contribution_budget_inr` and a regression test rejecting ₹5,000.001 (HTTP 422).
- Fresh valuation gate and stale-valuation regression remain present.
- The last inspectable Actions run (#2175 / run ID 44281293794) has all three jobs queued and belongs to the earlier head `550def791b193fe4a0d1da89e980a1d42418315c`, not this latest head. The connector's commit-run lookup returned no exact-head PR runs; therefore current-head CI is unverified. No tests are claimed as passed.
- No merge, production migration, deployment or production data changes were performed.


### TWT monthly comparison duplicate-key integrity — 2026-11-18

A further review found that the generic monthly comparison helper built dictionaries directly from snapshot rows. Duplicate scheme/category/AMC/sector identifiers could silently overwrite earlier rows, producing incomplete but apparently valid comparison deltas. Missing identifiers could also collapse into a shared `None` key.

- Added identifier validation before constructing comparison maps.
- Duplicate, blank or missing identifiers, and malformed rows now withhold that comparison section with `WITHHELD_DUPLICATE_OR_INVALID_KEYS`; no rows are silently dropped.
- Added regression tests for duplicate scheme codes and blank category identifiers.

Commits:
- `7cc08fb` — Fail closed on duplicate monthly comparison identifiers.
- `acea17d` — Test invalid and duplicate monthly comparison identifiers.

**Validation:** code and tests are committed; current-head CI must complete before this is marked passed. No merge, deployment or production data changes.


### TWT monthly source-value validation hardening — 2026-11-18

A follow-up audit found that monthly comparison deltas accepted impossible percentage values and could compare AMC concentration metrics even when allocation evidence was not in an allowed state. The risk lookback check also relied on Python's integer type check, which treats booleans as integers.

- Monthly allocation percentage deltas now withhold source values outside 0–100.
- Data-coverage percentage deltas now validate the same 0–100 bounds.
- AMC concentration comparisons now require allowed allocation status and validate AMC weights (0–100), HHI (0–10,000), and effective AMC count (>0).
- Boolean lookback windows are rejected even though `bool` subclasses `int` in Python.
- Added regressions for out-of-range allocation and coverage percentages, invalid AMC status/HHI, and boolean risk lookback.

Commits:
- `bb8c282` — Validate monthly comparison percentage source bounds.
- `7d5c239` — Test invalid monthly percentages and risk lookback types.
- `3c4f3d2` — Gate AMC deltas on valid allocation evidence.
- `e84cac9` — Test AMC monthly comparison evidence and bounds.
- `8b37f50` — Validate TWT monthly coverage percentage bounds.
- `0cfad63` — Test invalid monthly coverage percentage values.

**Validation:** committed implementation and regression coverage; no test pass is claimed until the exact current-head CI completes. No merge, deployment or production data changes.

### Portfolio intelligence UI contract and cache invalidation — 2026-11-18

Two frontend integration issues were found during a contract review:

- The look-through API returns security concentration under `security_concentration`; the overview diagnosis incorrectly read `concentration`, so its ISIN-identity warning could never appear. The renderer now reads the actual API field.
- The HTML kept static asset query keys at `v=2`; browsers/CDNs could continue serving an older JS/CSS bundle after deployment. Both portfolio-intelligence asset keys are bumped to `v=3`.

Added a UI contract regression test for both issues.

Commits:
- `44b21aa` — Bust portfolio intelligence static asset cache.
- `e174352` — Fix look-through concentration diagnosis field.
- `d066707` — Test portfolio UI cache and look-through API contract.

Validation pending on exact latest branch SHA. No merge or deployment.


### TWT AMC concentration cross-metric integrity — 2026-11-18

A further monthly-comparison audit found that individually in-range AMC metrics could still contradict one another. For example, top-1 concentration could exceed top-3, or HHI and effective AMC count could disagree while each value remained inside its standalone numeric bounds.

- Monthly comparison now validates each snapshot's top-1 ≤ top-3 ≤ top-5 ordering.
- For populated snapshots, HHI × effective AMC count must reconcile to 10,000 within a small rounding tolerance; the all-zero empty-allocation case remains valid.
- All AMC concentration deltas are withheld when either snapshot has internally inconsistent or out-of-range AMC evidence, rather than exposing a partially plausible set of metrics.
- Added regressions for inverted top-N ordering and contradictory HHI/effective-count values.

Commits:
- `4d50aa7` — Validate cross-metric AMC concentration consistency.
- `707feff` — Test inconsistent AMC concentration source metrics.
- `d2c31a7` — Fail closed on any inconsistent AMC source metric.

**Validation:** implementation and regression tests are committed. GitHub Actions has not reported a run or completed status for the exact latest head; no test pass is claimed. PR #135 remains open and draft. No merge, deployment, production migration or production data change was performed.

### Look-through percentage display scaling — 2026-11-18

A data-to-UI audit found that the backend already returns look-through concentration weights as percentage points (0–100), while the UI divided them by 100 before passing them to a formatter that does not multiply. This understated ISIN identity coverage and top-1/top-5/top-10 security concentration by 100x.

- Removed the extra division for ISIN identity coverage and top-N observed-positive weights.
- Bumped portfolio intelligence CSS/JS cache keys to `v=4` so clients cannot retain the previous renderer after deployment.
- Added regression coverage for percentage scaling and the new asset cache key.

Commits:
- `c077170` — Correct look-through percentage display scaling.
- `57b25da` — Test look-through percentage display scaling.
- `fe9d494` — Refresh portfolio intelligence asset cache after UI fix.
- `aea2ca0` — Assert latest portfolio intelligence asset cache key.

Validation pending on exact latest branch SHA. No merge or deployment.


AMC consistency guard follow-up: the cross-metric validation also checks available metric pairs when other AMC fields are missing, so partial evidence cannot bypass top-N ordering checks. Added a partial-evidence regression.

- `f0811ac` — Validate partial AMC concentration evidence consistently.
- `7afda9d` — Test partial AMC concentration inconsistency.

Exact-head CI remains the release gate; no pass is claimed.


### TWT monthly monetary and risk-source validation — 2026-11-18

A further snapshot-comparison audit found that malformed market-cap rows could raise during report comparison, and negative rupee values or impossible historical-risk values could still be treated as valid source metrics.

- Market-cap comparison now withholds malformed classified/unclassified row structures instead of raising.
- Monthly INR allocation values and portfolio valuation reject negative source amounts.
- Historical risk deltas now validate volatility (non-negative), drawdown (-100% to 0%), and historical VaR/CVaR (0–100% loss fraction) before exposing movement.
- Added regressions for malformed market-cap rows, negative INR/portfolio values, impossible drawdown and VaR.

Commits:
- `3d429a0` — Reject invalid monetary values and malformed market-cap rows.
- `318859c` — Test invalid monetary and market-cap monthly sources.
- `daa4c51` — Validate historical risk source metric bounds.
- `4d84a4e` — Test invalid monthly historical risk source values.

**Validation:** code and regression tests are committed; exact latest-head CI is still the release gate. No merge, deployment or production data changes.


### TWT risk comparison report-schema integration fix — 2026-11-18

Tracing the monthly report against the actual portfolio risk engine revealed a schema mismatch: `portfolio_risk_metrics` returns risk metrics at the top level of the `risk` object, while the monthly comparison reader only looked under `risk.metrics`. This silently withheld all risk deltas for normally generated snapshots.

- Monthly comparison now reads the actual top-level risk fields.
- Retains nested `risk.metrics` fallback for older immutable snapshots.
- Added an integration-shaped regression with the exact top-level schema emitted by the risk engine and assertions for volatility, drawdown, VaR and CVaR deltas.

Commits:
- `ca76d6d` — Read risk deltas from actual portfolio report schema.
- `b2dabe3` — Test monthly risk deltas against actual report schema.

**Validation:** committed; exact current-head CI is required before acceptance. No merge, deployment or production data changes.


### TWT risk-payload schema clarification — 2026-11-18

A final trace through the report assembly confirmed that the canonical saved-report shape is `risk.metrics`: the report builder calls the portfolio historical-risk endpoint, which wraps the risk engine output under `metrics`. The existing nested reader was already aligned with that canonical shape. The additional direct-field fallback and regression are retained as harmless compatibility support, not counted as a correction to the current report path.

- Clarified the code comment to document the canonical nested schema and compatibility fallback.
- Renamed the regression to describe the direct-field compatibility case accurately.
- Existing nested-risk regression cases continue to cover the canonical report shape.

No additional production change or release claim is made from this clarification.


### TWT latest implementation and validation checkpoint — 2026-11-18

- Monthly comparison now rejects negative INR source values, malformed market-cap rows and out-of-range historical risk metrics, with regression coverage.
- Risk comparison supports the canonical saved report `risk.metrics` structure and a direct-field compatibility fallback. The canonical nested schema was traced through report assembly and is already covered by the existing tests.
- The focused TWT monthly comparison test module now contains 29 test functions.
- Latest observed PR #135 head before this tracker update: `4c268b9a709ba1ec8e26ee878483d29e058d5253`; open, draft, mergeable.
- Latest observed CI run #2305 / run ID `44283468553`: SQLite, PostgreSQL and AMFI validation jobs are all queued. No pass is claimed.
- This update does not authorize merge or deployment. Production data, migrations and Render were not changed.


## TWT target-drift month-on-month completion — 2026-11-18

- Monthly report comparison now includes target allocation drift only when both frozen reports contain the same immutable target-policy version and effective date for every configured dimension.
- Each compared dimension must have a complete target set, unique bucket keys, valid actual weights and drift values, and actual weights reconciling to 100%. Changed bucket identities, changed policy versions, missing dimensions or incomplete snapshots are explicitly withheld.
- The comparison exposes actual-weight percentage-point movement and target-drift percentage-point movement separately. Drift is not represented as INR.
- Portfolio Intelligence now renders previous/current drift and the pp delta, alongside actual allocation weights.
- TWT PDF includes a dedicated target-drift movement table with previous/current drift pp, pp change and actual weights; withheld evidence includes its reason.
- Regression coverage added for comparable same-policy movement, policy-version changes, incomplete/reconciliation failures, PDF formatting and UI rendering.
- Static asset cache keys advanced to v5.
- Commits in this batch: `ce44e93`, `093e75c`, `dd4b457`, `c33312e`, `fc072c8`, `6aa7c69`, `792f087`, `6f87440`, `c173f68`, `c71f38a`, `365b16b`, `770f3f5`, plus tracker update `10905ae`.
- Validation: pending exact-head GitHub Actions; do not treat this work as test-passed until the SQLite, PostgreSQL and AMFI jobs complete successfully. Visual PDF pagination review remains open. No merge, deployment or production data changes.


### TWT immutable target-band cross-check — 2026-11-18

A deeper audit of monthly target-drift comparison found that it verified target bucket identities, target totals and drift arithmetic, but did not prove that each frozen drift row's minimum / preferred / maximum band still matched the immutable target-policy snapshot. A drift row could therefore be internally arithmetically consistent while representing a different target band from the policy version being compared.

- The comparison now validates every policy bucket has a unique non-empty key and a valid 0–100 min ≤ target ≤ max band.
- Every drift row must match the frozen policy's min, preferred target and max values exactly, in addition to matching its immutable version/effective date.
- Bucket keys must match exactly; target values must sum to 100%; actual weights must sum to 100%; and drift must reconcile to actual minus preferred target within the documented rounding tolerance.
- Added a regression where the drift rows are self-consistent and both target totals remain 100%, but the rows silently diverge from the immutable policy bands. The comparison now withholds this case.

Commits:
- `b8bdcfa` — Match frozen drift rows to immutable target policy bands.
- `c948a4b` — Test immutable target-band snapshot consistency.

**Validation:** changes and regression coverage are committed. Exact latest-head CI remains pending; no test pass is claimed. No merge, deployment, production migration or production data change.


### TWT PDF completeness and withheld-metric visibility — 2026-11-18

A PDF acceptance pass found two presentation/data-integrity gaps:

- The scheme allocation PDF table silently truncated portfolios after 40 schemes. It now renders every scheme in the immutable report snapshot; the table paginates rather than omitting the remaining scheme rows.
- Monthly PDF row status previously reflected only the INR metric. A percentage-point metric could be withheld as invalid while the row still displayed `COMPARABLE`. The displayed row status now reflects all included metrics (including both directional overlap denominators).

Regression coverage:
- A 45-scheme fixture asserts all 45 schemes reach the PDF table.
- A monthly row fixture asserts invalid percentage-point evidence is visibly withheld even when INR remains comparable.
- Existing overlap PDF fixture now supplies explicit status for both directional metrics.

Commits:
- `c045c88` — Include every scheme in TWT allocation PDF.
- `608104c` — Test PDF portfolios above 40 schemes.
- `44f6003` — Show withheld monthly metric status in PDF.
- `3f8c75f` — Test withheld monthly metric status visibility.
- `596c31d` — Correct overlap PDF regression fixture.

**Validation:** source and regression tests are committed. Exact latest-head CI remains required; no local test pass is claimed. No merge, deployment or production data change.
