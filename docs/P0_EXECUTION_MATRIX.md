# P0 Execution and Evidence Matrix

Last reviewed: 2026-11-16  
Repository: `yashvyas638/mf-terminal-intelligence-backend`  
Candidate branch: `audit/production-foundation`  
Production policy: **read-only inspection only until explicit release approval**

## Purpose and closure rule

P0 establishes the minimum security, data-integrity, operational and user-workflow foundation required before research analytics can be trusted. This matrix is the execution ledger for P0. A code change, passing unit test, green CI run, successful health probe or configured workflow is not closure evidence by itself.

Each gate closes only when its acceptance evidence is attached or linked, the exact commit/deployment/database revision is identified, and the result is reviewed. Unknown or unavailable evidence remains **BLOCKED**, never assumed PASS.

## Current evidence baseline

| Area | Known evidence | Current disposition |
|---|---|---|
| Candidate application | Supabase bearer-token validation, user ownership checks, portfolio workflows, migrations and simulated tenancy tests are present on this candidate branch | Implemented in code; live verification pending |
| Production database | Read-only SQL at 2026-11-16 09:51 UTC reports Alembic revision `0028_restrictive_private_access`; candidate now adds `0029_admin_default_acl` | Candidate 0029 is not yet deployed; verify CI, Render role and backup/restore before applying |
| Auth | Supabase Auth integration and browser flows exist; provider, redirect, SMTP delivery and real browser confirmation/reset are not evidenced | BLOCKED |
| Tenancy | Read-only SQL at 2026-11-16 09:51 UTC found 1 confirmed user, 0 portfolios, 0 portfolio owners, 1 goal, no unconfirmed goal owner and no cross-owner goal link | BLOCKED: no demonstrated two-account production isolation |
| Backups | Encrypted backup workflow requires database, age recipient and S3/R2 credentials; earlier run stopped at configuration preflight | BLOCKED: no successful off-site backup or isolated restore evidence |
| P0 audit workflow | Read-only audit workflow and expanded ownership/default-ACL checks exist; earlier run stopped because `SUPABASE_DB_URL` and `MF_TERMINAL_API_KEY` were absent | BLOCKED: required GitHub Actions secrets not verified |
| NAV | Latest production feed snapshot was retrieved 2026-11-12 02:53 UTC with max NAV date 2026-11-11. The scheduled NAV-refresh and AMFI-monitor workflows exist only on the candidate branch; default `main` has neither, and its `render.yaml` has no Cron service | BLOCKED: production refresh scheduler is not active/evidenced |
| Historical NAV | Official AMFI history response contract checks passed in CI. Live checkpoint inventory: 168 completed daily + 144 completed month-end checkpoints; 780 paused daily checkpoints are intentionally superseded by the hybrid plan, not failures | Hybrid history plan is populated; execution remains operator-gated and coverage must be reconciled by scheme/window |
| Render | `main/render.yaml` declares `mf-terminal-nav-api` on Starter with Uvicorn-only startup; candidate `render.yaml` declares `mf-terminal-intelligence-backend` on Free and runs `alembic upgrade head` before Uvicorn. Actual Render service, plan, branch, deployed SHA and DB role are unverified | BLOCKED: blueprint mismatch must be reconciled before sync/deploy |
| Browser workflow | API/UI flows exist, but complete real-browser end-to-end evidence is pending | BLOCKED |

This baseline is historical evidence, not a claim that the values remain current. Re-run read-only checks before release and record timestamps.

## Branch integration status

- Existing PR [#1](https://github.com/yashvyas638/mf-terminal-intelligence-backend/pull/1) targets `main` from `audit/production-foundation`.
- GitHub compare reports the branch as diverged: **604 commits ahead, 53 behind**, with 145 changed files (133 added, 12 modified). The diff includes the application, migrations, UI, CI/operations workflows and product documentation—not just the P0 hardening changes.
- GitHub currently reports the PR as `mergeable=false` / `mergeable_state=dirty`. No merge, rebase, force-push or branch reset has been attempted.
- P0 closure requires a reviewed integration plan: reconcile the 53 commits on `main`, review the full 145-file diff, identify conflicts, and confirm the intended application release before merge.
- Candidate-side content reconciliation is now complete for the four P0 overlap files: the audit script combines goal/portfolio ownership checks with effective default-ACL and backfill checks; the backup workflow preserves the encrypted archive, verifies downloaded R2 size/SHA-256 and cleans up with `always()`; the P0 workflow retains redacted blocked-configuration evidence; and the runbook includes the latest verified project state and closure evidence. This does **not** resolve Git history conflicts; GitHub still reports the PR as not mergeable.

## External configuration blockers

Latest GitHub Actions secret preflight reported these names missing (values were not accessed):
- `SUPABASE_DB_URL`
- `MF_TERMINAL_API_KEY`
- `BACKUP_AGE_RECIPIENT`
- `BACKUP_S3_BUCKET`
- `BACKUP_S3_ENDPOINT`
- `BACKUP_S3_ACCESS_KEY_ID`
- `BACKUP_S3_SECRET_ACCESS_KEY`

Latest P0 audit run evidence: [GitHub Actions run #43827121017](https://github.com/yashvyas638/mf-terminal-intelligence-backend/actions/runs/43827121017) passed Python audit syntax validation, failed configuration preflight on the missing `SUPABASE_DB_URL` and `MF_TERMINAL_API_KEY`, and skipped database execution. Its redacted diagnostic artifact is `14207405856` (358 bytes; SHA-256 `6eadfb410c007d86fc6eed648ffbf391fb687aab91bfbc3b4dbb482e122cbadd`; expires 2026-12-16).

Default-branch backup workflow defect: fixed on `main` in commit `8a32616511c88a109e41ae4c782bb25e2b2bb82b`. The R2 step now imports `STAMP` from `steps.backup.outputs.stamp`, downloads the uploaded object and verifies size plus SHA-256 for daily and monthly copies. The push-triggered run stopped at configuration preflight because required secrets are absent; no database export or production connection was attempted. The candidate validator now rejects a cross-step `$STAMP` reference unless it is explicitly imported from the prior step output.

The backup workflow cannot produce/verify an offsite encrypted backup until the backup secrets are configured. The P0 audit cannot complete its authenticated API/database checks until its required secrets are configured. Render environment values and the live service's selected branch/plan remain unverified.

## Candidate CI evidence

- Candidate code-verification commit: `8aeb78f150a9d2e0f0da876d36b147f45baff65c`; this matrix update is documentation-only.
- Latest candidate run [#43850643962](https://github.com/yashvyas638/mf-terminal-intelligence-backend/actions/runs/43850643962): **all three jobs passed** (SQLite, PostgreSQL, live AMFI source validation).
- PostgreSQL CI: **359 passed**, 1 non-blocking warning; migration chain reached `0029_admin_default_acl`.
- SQLite migrations and tests, lint, dashboard/research/fund-detail/password-screening JavaScript checks, Node URL-safety tests, operational workflow/Render/backup/P0 validator, and authentication/portfolio DOM contracts: passed.
- Live AMFI historical response contract checks for scheme types 1, 2 and 3: passed. Performance taxonomy contract, 43-category read-only coverage audit and official scheme-summary metadata probe: passed. No production database writes were performed.

## Code-level tenancy evidence

- `tests/test_supabase_auth.py` simulates two distinct verified Supabase identities and exercises portfolio, transaction, import, stress, void, audit, report, watchlist and goal ownership boundaries.
- Dashboard and Research tests exercise A→B→A account switches and reject late responses from a previous session.
- These are valuable code-level tests, but they do not prove real Supabase signup/confirmation, actual JWT issuance, SMTP delivery, browser persistence, or two real production accounts. Those remain release gates.

## Latest live Supabase read-only audit — 2026-11-16 09:51 UTC

Project: `zgfdvhzhvccsfmpoaqah`. No DDL or data writes were performed.

- Alembic revision: `0028_restrictive_private_access`. The Supabase MCP migration-list endpoint returned an empty list; this application uses Alembic, so `public.alembic_version` is the authoritative application migration record.
- Data counts: 16,143 schemes; 2,664,820 NAV observations; 317 ingestion snapshots; 34,852 research snapshots; 1,092 historical backfill checkpoints; 0 portfolios; 0 portfolio transactions; 1 portfolio goal.
- Auth/ownership: 1 confirmed Auth user; the single goal belongs to a confirmed Auth user; no cross-owner goal link was found. No portfolio rows exist, so a two-account isolation test is not yet possible.
- RLS: enabled on all 21 inspected public tables. Effective privileges for `anon` are denied on all inspected tables. `authenticated` has SELECT only on the intended six read surfaces (`schemes`, `nav_observations`, `portfolios`, `portfolio_transactions`, `portfolio_transaction_audit`, `portfolio_import_batches`) and no INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER privileges.
- Private-table posture: restrictive deny-all policies are present for the private user/internal tables. Eleven RLS-enabled tables have no policies; the advisor notices are informational because direct client grants are denied.
- Sequences: no `anon` or `authenticated` USAGE/SELECT privileges were found across the 18 public sequences.
- Functions: the two public financial guard trigger functions are SECURITY INVOKER, pin `search_path=pg_catalog, public`, and are executable by `service_role` but not by `anon` or `authenticated`.
- Default privileges: effective defaults for `postgres`, `pg_database_owner` and `supabase_admin` include built-in `PUBLIC EXECUTE` for future functions; `supabase_admin` also has explicit `anon`/`authenticated` grants for future public tables, sequences and functions. Candidate migration `0029_admin_default_acl` revokes global and schema-specific PUBLIC/client defaults for every role able to CREATE in `public`; production remains at 0028 until approved.
- Security Advisor: one warning for native leaked-password protection disabled; 11 informational RLS-enabled/no-policy findings on deny-all tables. Health Advisor: no findings. Performance Advisor: 24 unused-index INFO notices; do not drop indexes without workload evidence.
- SQL inspection reported `current_user=postgres` with `rolsuper=false`, `rolbypassrls=true`, `rolcreaterole=true` and `rolcreatedb=true`. This is a powerful Supabase audit role, not proof of the Render backend connection role or a least-privilege runtime role.

The native Supabase leaked-password protection warning is separate from the future-object ACL issue. The browser-side Pwned Passwords mitigation is not equivalent to server-side Auth enforcement.

- Official AMFI performance/taxonomy live audit on report date `13-Nov-2026`: 43 categories checked, 86 requests, 2,140 rows, 2,073 current allowlisted identifiers and 67 legacy/rejected rows retained as diagnostic-only. The audit performed zero database writes. The official scheme-summary probe also returned scheme details and category/manager fields for sampled schemes.
- NAV freshness: the latest daily-feed snapshot was retrieved at `2026-11-12 02:53 UTC`, with maximum effective NAV date `2026-11-11`. No later accepted daily-feed snapshot was present at audit time.
- Historical backfill checkpoints: 168 daily complete, 144 month-end complete, and 780 daily paused. The paused rows carry `StorageOptimizedHybridPlan` because the hybrid planner deliberately superseded the original all-daily plan. They are not failed requests. No pending or running checkpoints were present.
- Workflow activation: candidate `nav-refresh.yml` and `amfi-live-source-check.yml` are not present on default `main`. The current default-branch `render.yaml` contains one web service and no Cron service. A schedule on a non-default branch is not an active GitHub scheduled workflow.

## Gate register

### P0-0 — Release governance and reproducibility

**Build requirements**
- Keep candidate application work isolated on `audit/production-foundation`.
- Record exact candidate SHA, changed files, migration head, CI run and test summary for every implementation batch.
- Confirm candidate work does not overwrite unrelated work on `main`.
- Do not deploy, run production migrations, create test users, mutate production portfolios or trigger production data changes without explicit approval.

**Acceptance evidence**
- [ ] Candidate SHA and branch recorded.
- [ ] PR branch divergence/conflicts are reconciled without dropping unrelated `main` work or silently importing unrelated application changes.
- [ ] GitHub diff reviewed; no secrets or local data committed.
- [ ] Required CI jobs pass on the exact candidate SHA.
- [ ] Migration head and ordered migration list recorded.
- [ ] Production deploy/migration approval recorded separately.

### P0-1 — Secrets and operational configuration

**Build requirements**
- Validate required configuration before any network/database operation.
- Keep secrets out of source, logs, artifacts and chat.
- Ensure missing configuration produces a clear, redacted failure artifact and never a false green result.
- Rotate any credential previously exposed; coordinate Render and GitHub secret stores without disclosing values.

**Required secret inventory**
- P0 audit: `SUPABASE_DB_URL`, `MF_TERMINAL_API_KEY`.
- Encrypted backup: `SUPABASE_DB_URL`, `BACKUP_AGE_RECIPIENT`, `BACKUP_S3_BUCKET`, `BACKUP_S3_ENDPOINT`, `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY`.
- Render: least-privilege runtime PostgreSQL `DATABASE_URL`, privileged direct-session migration-only `MIGRATION_DATABASE_URL` (not a transaction-pooler URL), operator `API_KEY`, Supabase URL and publishable key, plus required provider settings.

**Acceptance evidence**
- [ ] Every required secret exists in its correct secret store.
- [ ] Runtime `DATABASE_URL` and migration-only `MIGRATION_DATABASE_URL` are separate; the privileged migration URL is never used by the running API process.
- [ ] Secret presence is validated without printing values.
- [ ] Operator API key is rotated and matches between authorised services.
- [ ] Audit and backup workflows pass configuration preflight.

### P0-2 — Authentication and account lifecycle

**Build requirements**
- Verify signup, confirmation email, sign-in, session restoration/refresh, password reset request, reset link, password update and sign-out in a real browser.
- Validate Supabase Site URL, redirect allow-list, email provider and SMTP delivery.
- Confirm native leaked-password protection is enabled. If the current Supabase plan does not support it, record an explicit risk acceptance or upgrade; browser-side Pwned Password screening is not equivalent and can be bypassed through direct Auth API calls.
- Confirm protected API routes reject missing, malformed, expired and invalid bearer tokens.
- Confirm operator-only routes reject browser bearer-only access where the server key is required.
- Ensure logout clears private UI state and stale cached account data.

**Acceptance evidence**
- [ ] Real signup and confirmation completed for test account A.
- [ ] Login, reload/session restoration, refresh and logout pass.
- [ ] Password reset email is received and password update succeeds.
- [ ] Native leaked-password protection is enabled or the limitation is formally accepted with compensating controls.
- [ ] Invalid/expired token requests are rejected.
- [ ] No account/session material is leaked in logs or frontend storage beyond the provider's intended session mechanism.
- [ ] Evidence includes browser version, timestamp, environment and redacted result.

### P0-3 — Multi-user ownership and database security

**Build requirements**
- Audit every portfolio-scoped API path, including goals, transactions, import preview/commit, void/audit, valuation, rebalance and report/watchlist features.
- Verify every query is scoped to the authenticated owner; never trust a user-supplied owner ID.
- Compare the complete candidate Alembic migration chain with live Supabase schema, indexes, constraints, triggers, grants, RLS and functions.
- Verify Render runtime uses a least-privilege trusted server-side PostgreSQL role, not `anon` or `authenticated`; Alembic uses a separate privileged `MIGRATION_DATABASE_URL`.
- Verify RLS and grants on every public table, including global and schema-specific default privileges for every object-creating role, sequences and functions. Confirm intended client-readable allowlist and deny-all internal tables.
- Verify security-definer functions use a fixed safe `search_path` and least-privilege execution grants.
- Test horizontal privilege escalation using two real accounts.

**Acceptance evidence**
- [ ] Live schema-to-migration diff reviewed with no unexplained drift.
- [ ] Migration `0029_admin_default_acl` passes PostgreSQL CI and the live effective-default-ACL audit reports no client/PUBLIC grants before production approval.
- [ ] Actual migration connection is confirmed superuser/member of every public-schema creator role; otherwise use an approved privileged migration process.
- [ ] Actual Render database role confirmed privately.
- [ ] Every table, sequence and function privilege is reconciled.
- [ ] No global or schema-specific default privilege grants future public objects to `PUBLIC`, `anon` or `authenticated` for any creator role.
- [ ] RLS enabled and intended policies verified for each relevant table.
- [ ] Account A cannot read, update, void, import into or infer Account B's records; reverse test also passes.
- [ ] Goal-to-portfolio owner mismatch and orphan-link cases are rejected.
- [ ] Append-only ledger/audit/NAV revision invariants pass against PostgreSQL.
- [ ] No production migration executed before approval and a verified recovery path.

### P0-4 — Backup, off-site retention and restore

**Build requirements**
- Create a consistent logical export of supported application schemas/data and role definitions.
- Encrypt before upload; do not retain plaintext in workflow artifacts or logs.
- Require off-site R2/S3 storage; GitHub artifact is secondary only.
- Verify uploaded object size and cryptographic checksum by downloading the object back and checking bytes.
- Record explicit backup scope exclusions: Supabase-managed Auth/Storage/extension schemas and Storage object bytes are not included by the current CLI logical dump.
- Restore into a separate isolated project and reconcile schema, migration state, row counts, constraints, grants, RLS and application smoke tests.
- Keep the private age identity offline; only its public recipient belongs in Actions secrets.

**Acceptance evidence**
- [ ] First encrypted backup workflow succeeds end-to-end.
- [ ] R2/S3 object download-back checksum matches local encrypted artifact.
- [ ] Backup manifest, timestamp, object key and checksum are recorded without secrets.
- [ ] Isolated restore succeeds with no unresolved SQL errors.
- [ ] Restored schema/data counts reconcile to source snapshot.
- [ ] Application tests and security posture checks pass against restored target.
- [ ] Recovery time and recovery point are measured and recorded.

### P0-5 — AMFI latest NAV ingestion integrity

**Build requirements**
- Verify the live official AMFI response, parser version, content type, byte size, source hash, retrieved timestamp and effective NAV date.
- Enforce minimum valid records and reject malformed, empty, stale, future-dated or unexpectedly small source responses without replacing accepted data.
- Verify exact replay idempotency and correction provenance.
- Verify missing ISIN values never erase known identifiers or get fabricated.
- Confirm the scheduled refresh workflow is present on default `main` or a production Cron service is configured, has required secrets and succeeds on its intended cadence. A workflow present only on the candidate branch is not an active production schedule.
- Expose ingestion freshness, effective-date freshness, snapshot quality and accepted/rejected counts to operators.

**Acceptance evidence**
- [ ] Live source validation passes and records source hash/metadata.
- [ ] Production refresh creates one accepted snapshot with expected record counts.
- [ ] Exact replay creates no duplicate NAV observations or false revisions.
- [ ] Controlled correction fixture creates append-only prior/replacement provenance.
- [ ] Bad-source fixtures fail closed and preserve the last accepted snapshot.
- [ ] Production refresh scheduler is active on the deployed/default branch or an approved Render Cron service.
- [ ] Scheduled refresh has at least one successful observed run after activation.
- [ ] Freshness and effective-date status are visible and alertable.

### P0-6 — Historical NAV contract and coverage

**Build requirements**
- Capture the official AMFI historical NAV form request and response for each supported scheme type.
- Preserve sanitized fixtures and document parameters, date format, encoding, row layout, pagination/limits and error responses.
- Keep the documented maximum range validation and conservative checkpoint windows.
- Validate retry/resume, duplicate replay, correction handling and per-scheme coverage.
- Do not enable history execution until the source contract is verified; never substitute an unofficial mirror as canonical data.

**Acceptance evidence**
- [ ] Official source request/response contract independently reproduced.
- [ ] Sanitized fixtures cover supported response variants and failure cases.
- [ ] Parser fixture tests pass and date/value reconciliation is documented.
- [ ] A bounded historical backfill is run only after explicit operator enablement.
- [ ] Coverage report shows scheme count, date span, gaps and last successful backfill.
- [ ] Superseded paused checkpoints are distinguished from failed/pending work; hybrid coverage is reconciled by sampling mode.
- [ ] Ranking windows with insufficient baseline data are withheld, not fabricated.

### P0-7 — Portfolio workflow and ledger correctness

**Build requirements**
- Complete authenticated first-run, portfolio creation, BUY/SELL entry, CSV preview, confirmed import, valuation, transaction history and audited void.
- Verify arithmetic, Decimal precision, chronological unit balances, oversell prevention, duplicate import rejection and idempotency.
- Verify partial NAV coverage withholds aggregate metrics that cannot be supported.
- Confirm all workflows persist across reload and fresh login.
- Keep test data isolated and identifiable; do not delete real production financial records as test cleanup.

**Acceptance evidence**
- [ ] Account A creates and reads its own portfolio.
- [ ] BUY/SELL and transaction ledger reconcile to units, cost and cash flow.
- [ ] CSV preview performs no writes; confirmation commits atomically.
- [ ] Duplicate import is rejected without duplicate transactions.
- [ ] Invalid arithmetic, negative units and oversell are rejected.
- [ ] Void is reasoned, audited, one-time and non-destructive.
- [ ] Missing NAV produces explicit partial status and no fabricated aggregate gain/loss or XIRR.
- [ ] Portfolio state survives logout/login and is not visible to Account B.

### P0-8 — Render deployment, API smoke tests and rollback

**Build requirements**
- Verify deployed service, branch, exact SHA, runtime, environment configuration and startup command.
- Verify startup runs the approved Alembic migration process and rejects unsafe DB roles.
- Run endpoint smoke tests for health, NAV status, scheme search/detail/history, portfolio lifecycle and auth.
- Record deploy ID, migration head, logs, previous known-good deploy and rollback route.
- Do not infer deployment state from environment variable presence or a successful health endpoint alone.

**Acceptance evidence**
- [ ] Actual Render service, service identity, plan and deployed SHA verified.
- [ ] Candidate Render blueprint is reconciled with the existing service; no accidental new service, service rename or plan change is introduced.
- [ ] Actual PostgreSQL connection role verified privately and proven able to run the approved migration chain.
- [ ] Migration head matches approved candidate.
- [ ] Required endpoints pass with correct authentication/authorization.
- [ ] No secret or sensitive portfolio data appears in logs.
- [ ] Previous deploy and rollback path are recorded.
- [ ] Post-deploy data integrity checks show no unexpected row-count or ledger changes.

### P0-9 — Monitoring and operational failure handling

**Build requirements**
- Distinguish service health from NAV freshness and effective-date freshness.
- Alert on missed refresh, stale data, failed backfill, failed snapshot rebuild, backup failure and failed audit.
- Preserve redacted run artifacts and enough metadata to diagnose failures.
- Document operator response and recovery actions.

**Acceptance evidence**
- [ ] Health and data-freshness checks are independent.
- [ ] At least one controlled alert test is observed.
- [ ] Failure artifacts are redacted and retained.
- [ ] Operator runbook describes retry, stop, escalation and recovery.

## P0 execution order

1. Correct stale/contradictory documentation and reconcile candidate branch scope.
2. Inspect and harden code-level Auth, ownership, database privilege and migration checks.
3. Build automated negative tests for every owner-scoped endpoint and ledger invariant.
4. Harden backup/audit workflows and produce redacted failure evidence when configuration is absent.
5. Complete AMFI live-source and historical contract validation without enabling unsafe production writes.
6. Complete browser workflow automation and two-account test harness.
7. Once secrets and approvals are supplied in their proper systems, execute live verification and isolated restore.
8. Reconcile all evidence, fix failures, rerun exact-SHA CI, then request explicit release approval.

## P0 sign-off

P0 status remains **OPEN — BLOCKED** until every mandatory gate above is closed. A warning is not a pass. A simulated test is not a real-account test. A backup upload is not a restore drill. A health check is not a data-quality check. CI is not production verification.

Final sign-off record:
- Candidate branch/SHA:
- CI run(s):
- Candidate Alembic head:
- Production Alembic revision:
- Render deploy ID/SHA:
- Render database role:
- Auth/browser evidence:
- Two-account isolation evidence:
- Grants/RLS/function audit:
- Encrypted backup object/checksum:
- Isolated restore evidence:
- AMFI latest snapshot/source hash:
- Historical NAV contract/coverage:
- Portfolio workflow evidence:
- Rollback reference:
- Remaining limitations:
- Explicit release approval:
