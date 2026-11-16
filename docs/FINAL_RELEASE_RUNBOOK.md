# Final Production Release Runbook

This runbook is intentionally prepared during development and executed only at the final release gate. It does not authorize production changes by itself.

## Release invariants

- Candidate branch: `audit/production-foundation`.
- `main` remains untouched until explicit approval.
- Never paste secrets into chat, issues, commits, CI output or screenshots.
- Never reset, truncate, drop or bulk-rewrite production tables.
- Do not deploy while the Render dashboard/deployment history is inaccessible.
- Do not apply permission migrations until the actual Render database connection role is verified.
- Back up Supabase and prove the backup can be restored to a non-production project before production migration.

## Candidate migration chain

The production database was read-only verified at Alembic revision `0028_restrictive_private_access` on 2026-11-16 09:51 UTC. The candidate branch now adds `0029_admin_default_acl`, which revokes unsafe `supabase_admin` default grants to `anon` and `authenticated` for future public tables, sequences and functions. Production remains at 0028 until an approved deployment. The current SQL inspection ran as `postgres`; this does not identify Render's actual backend role.

| Order | Revision | Purpose |
|---:|---|---|
| 1 | `0001_schema_baseline` | Original application schema baseline |
| 2 | `0002_portfolio_ledger_audit` | Portfolio ledger audit and void fields |
| 3 | `0003_nav_correction_history` | Append-only NAV correction provenance |
| 4 | `0004_restrict_supabase_client_roles` | Revoke direct client-role table/sequence/function privileges |
| 5 | `0005_portfolio_import_dedup` | Per-portfolio normalized statement fingerprints |
| 6 | `0006_ledger_db_constraints` | Financial database CHECK constraints |
| 7 | `0007_append_only_audit` | Protect portfolio audit and NAV correction history from mutation |
| 8 | `0008_scheme_classification` | Canonical scheme classification fields |
| 9 | `0009_audit_function_search_path` | Harden audit function search path |
| 10 | `0010_user_auth_rls` | Authenticated portfolio ownership and database RLS |
| 11 | `0011_research_security_tuning` | Tune RLS evaluation and foreign-key indexes |
| 12 | `0012_nav_backfill_checkpoints` | Durable historical NAV backfill checkpoints |
| 13 | `0013_user_fund_watchlists` | Per-user fund watchlists |
| 14 | `0014_fund_research_snapshots` | Precomputed research snapshots for screener rankings |
| 15 | `0015_benchmark_tri_foundation` | Source-provenanced benchmark TRI observations and mappings |
| 16 | `0016_fund_holdings_disclosures` | Immutable source-provenanced holdings disclosures |
| 17 | `0017_portfolio_goals` | Owner-isolated financial goals |
| 18 | `0018_portfolio_report_snapshots` | Immutable owner-scoped portfolio reports |
| 19 | `0019_goal_portfolio_link` | Link goals to owner-scoped portfolios |
| 20 | `0020_foreign_key_lookup_indexes` | Index foreign-key lookup paths |
| 21 | `0021_expand_scheme_option_type` | Widen scheme option text for AMFI descriptions |
| 22 | `0022_nav_history_sampling_mode` | Historical NAV checkpoint sampling mode |
| 23 | `0023_screener_period_returns` | Persist displayed trailing-period screener returns |
| 24 | `0024_research_windows` | Align research snapshots to 1M, 1Y, 3Y and 5Y |
| 25 | `0025_portfolio_txn_idempotency` | Durable transaction-creation idempotency |
| 26 | `0026_api_rate_limit_buckets` | Shared database-backed API rate-limit buckets |
| 27 | `0027_private_access` | Deny direct Supabase client access to private user tables |
| 28 | `0028_restrictive_private_access` | Make private-table denial policies restrictive |
| 29 | `0029_admin_default_acl` | Revoke `supabase_admin` default client grants for future public objects |

The migrations are forward-only where they protect financial evidence or security posture. Downgrades must not remove audit/provenance or restore broad client privileges. Rollback is normally an application-code redeploy plus a reviewed forward-fix, not an Alembic downgrade.

Before release, re-read the migration tree and confirm the candidate head is `0029_admin_default_acl` or a subsequently reviewed revision; production currently reports `0028_restrictive_private_access`. This runbook is a snapshot, not a substitute for inspecting the exact SHA. The 0029 migration must be tested on PostgreSQL CI and requires `MIGRATION_DATABASE_URL` authorised to alter default privileges for every role able to CREATE in `public`. The API runtime uses only `DATABASE_URL`; do not reuse the privileged migration URL for normal application queries. The latest Supabase SQL inspection ran as `postgres`, which is not a member of `supabase_admin`; do not assume that connection can apply 0029. The migration preflights this and aborts before changes if authority is insufficient. Use an approved privileged migration process if Render's actual database role lacks the required membership.

## Pre-deployment checks

- [ ] Confirm the exact candidate commit SHA on GitHub and all required CI jobs are green on that SHA.
- [ ] Confirm no uncommitted local work is expected; GitHub remote status cannot prove a local working tree is clean.
- [ ] Inspect the full migration diff and compare live Supabase schema, indexes, constraints, grants and RLS with the migration chain.
- [ ] Take a fresh Supabase backup and record its timestamp/reference.
- [ ] Verify the backup restore in an isolated non-production project.
- [ ] In a private Render environment inspection, identify the actual PostgreSQL role used by the backend. Do not disclose the connection string.
- [ ] Confirm the deployed candidate includes the startup guard that queries `current_user` and rejects `anon`/`authenticated`; this guard is a fail-closed defence, not a substitute for private Render role inspection.
- [ ] Confirm Render runtime `DATABASE_URL` uses a least-privilege trusted backend role, not `anon`, `authenticated`, or an untrusted Data API path.
- [ ] Configure a separate privileged, direct-session PostgreSQL `MIGRATION_DATABASE_URL` for Alembic only (not a transaction-pooler URL). It must be authorised to alter defaults for every public-schema creator; the API runtime must not inherit this migration credential.
- [ ] Verify all public-schema object creators and their effective global plus schema-specific defaults. Candidate migration `0029_admin_default_acl` removes global and `public`-schema PUBLIC/client defaults for tables, sequences and functions for every role able to CREATE in `public`; the migration connection must be authorised for each creator role.
- [ ] Confirm the candidate's Supabase bearer-token authentication and owner-scoped API checks match the live grants/RLS design. Do not assume candidate migrations or simulated tenancy tests have been applied or verified in production; prove the Render role, schema revision and two-account isolation first.
- [ ] Reconcile the Render blueprint before any sync/deploy. `main/render.yaml` declares `mf-terminal-nav-api` on Starter with Uvicorn-only startup; candidate `render.yaml` declares `mf-terminal-intelligence-backend` on Free and runs `alembic upgrade head` before Uvicorn. The actual Render service, plan, deployed branch and start command are not verified. Do not sync until the intended service identity, plan, environment and migration role are confirmed; avoid accidental service creation, rename or plan downgrade.

- [ ] Confirm a NAV refresh scheduler is active on default `main` or as an approved Render Cron service. The candidate `nav-refresh.yml` and `amfi-live-source-check.yml` files are not active while they exist only on `audit/production-foundation`; neither branch's `render.yaml` defines a Cron service.
- [ ] Confirm scheduler secrets, endpoint URL, cadence, last successful run and alerting. NAV retrieval freshness must be under 36 hours and effective NAV age within the configured maximum.

## Secret rotation

Rotate the API key that was previously exposed. Generate a new random value of at least 32 characters in a password manager. Update privately:
- Render runtime environment variable `DATABASE_URL` (least-privilege app role)
- Render migration-only secret `MIGRATION_DATABASE_URL` (privileged Alembic role)
- Render environment variable `API_KEY`
- GitHub Actions secret `MF_TERMINAL_API_KEY`

Also verify GitHub Actions secret `MF_TERMINAL_API_URL` contains the service base URL without a trailing slash. Never copy secret values into this runbook or chat.

## GitHub Actions secret preflight

The latest secret preflight reported these names missing; secret values were not accessed:
- `SUPABASE_DB_URL`
- `MF_TERMINAL_API_KEY`
- `BACKUP_AGE_RECIPIENT`
- `BACKUP_S3_BUCKET`
- `BACKUP_S3_ENDPOINT`
- `BACKUP_S3_ACCESS_KEY_ID`
- `BACKUP_S3_SECRET_ACCESS_KEY`

Configure them privately in [GitHub Actions secrets](https://github.com/yashvyas638/mf-terminal-intelligence-backend/settings/secrets/actions) before expecting the P0 audit or encrypted offsite backup workflow to complete. Do not paste values into chat, commit them, or add them to this runbook.

## Database migration execution

Only after all pre-deployment checks and explicit release approval:
1. Confirm the intended Render service is connected to the authorised branch/commit.
2. Deploy the exact candidate SHA.
3. Confirm the approved Render start command runs Alembic with `MIGRATION_DATABASE_URL`, unsets that variable, then starts Uvicorn. The current `main` blueprint does not run Alembic at startup; the candidate blueprint does. Do not assume the live service matches either file.
4. Inspect deploy logs for migration success; redact secrets from any evidence.
5. Query the database privately and verify `alembic_version.version_num` matches the exact approved candidate migration head; never hard-code a historical revision when the candidate chain has advanced.
6. Verify `anon` and `authenticated` have no unintended table/sequence/function access, including inherited PUBLIC grants.
7. Verify append-only triggers exist on `portfolio_transaction_audit`, `nav_observation_revisions` and `portfolio_import_batches`; verify portfolio transaction fact columns cannot be updated/deleted and a one-time audited void is allowed.
8. Confirm no portfolio, scheme, snapshot, NAV or correction-history row counts unexpectedly changed.

## Production smoke tests

Run with the rotated API key in a private terminal or authorised test client; do not paste it into chat.

- [ ] `GET /health` returns `status=ok` and `database=reachable`.
- [ ] `GET /v1/nav/status` returns the latest persisted snapshot and freshness.
- [ ] `GET /v1/nav/schemes` returns a paginated scheme list.
- [ ] Run the official AMFI live-source validation workflow from the activated production workflow.
- [ ] Verify the daily refresh workflow is enabled on the default branch or an approved Render Cron service and observe one successful scheduled run.
- [ ] Trigger one authenticated `POST /v1/nav/refresh`; verify record count, payload hash, NAV effective-date age, quality report and persisted snapshot.
- [ ] Replay the same source; verify no duplicate scheme/date NAV rows and no false correction events.
- [ ] Verify a corrected NAV creates a revision preserving previous/replacement values and source snapshot IDs.
- [ ] Create a test portfolio only after agreeing how test records will be identified and retained; do not delete production financial records to clean up.
- [ ] Preview a small valid CSV; verify preview creates no transactions.
- [ ] Confirm import; verify transaction count, audit records and valuation.
- [ ] Re-submit the same normalized statement; verify HTTP 409 and no duplicate transactions.
- [ ] Verify invalid oversell, expired/altered confirmation token and invalid financial values are rejected.
- [ ] Verify portfolio transaction financial facts cannot be updated/deleted, void metadata can be set only once with a reason, and audit/import/NAV provenance rows cannot be updated/deleted.
- [ ] Verify missing NAV yields partial valuation and does not fabricate aggregate gain/loss or XIRR.
- [ ] Verify the dashboard loads, searches schemes, previews/commits imports and shows portfolio valuation.

## Rollback and incident response

- Record previous successful Render deploy ID and commit SHA before release.
- If the new application code fails before migrations, redeploy the last known-good application release.
- If migrations have run, do not blindly downgrade. Assess backward compatibility; prefer a forward fix.
- If data integrity is at risk, stop writes, preserve logs and use the approved backup/restore procedure in a separate controlled change.
- Re-run health, NAV status, portfolio valuation and audit smoke tests after recovery.
- Record incident, affected SHA, deploy ID, migration revision, backup reference and recovery result.

## Release sign-off record

Complete only after the production evidence exists:
- Candidate SHA:
- CI run URLs:
- Supabase migration revision:
- Supabase backup/restore evidence:
- Render deploy ID:
- Render deployed SHA:
- Database role verified:
- API key rotated:
- AMFI refresh snapshot ID:
- Portfolio import/valuation smoke test:
- Audit immutability check:
- Previous known-good deploy:
- Rollback procedure verified:
- Outstanding limitations:
- Explicit user sign-off:
