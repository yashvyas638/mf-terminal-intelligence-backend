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

The candidate branch has advanced to Alembic revision `0028_restrictive_private_access` (verified from the migration file tree at candidate SHA `357aeeb82eca834cd8aec8a909cfa4d4a86966ee`). The last production revision observed in the read-only Supabase audit was `0007_append_only_audit`. This is a substantial schema/security gap: do not deploy or apply the later migrations until the entire chain is reviewed against live schema, actual Render database role, backup and isolated restore evidence.

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

The migrations are forward-only where they protect financial evidence or security posture. Downgrades must not remove audit/provenance or restore broad client privileges. Rollback is normally an application-code redeploy plus a reviewed forward-fix, not an Alembic downgrade.

Before release, re-read the migration tree and confirm the head has not advanced beyond `0028_restrictive_private_access`; this runbook is a snapshot, not a substitute for inspecting the exact SHA.

## Pre-deployment checks

- [ ] Confirm the exact candidate commit SHA on GitHub and all required CI jobs are green on that SHA.
- [ ] Confirm no uncommitted local work is expected; GitHub remote status cannot prove a local working tree is clean.
- [ ] Inspect the full migration diff and compare live Supabase schema, indexes, constraints, grants and RLS with the migration chain.
- [ ] Take a fresh Supabase backup and record its timestamp/reference.
- [ ] Verify the backup restore in an isolated non-production project.
- [ ] In a private Render environment inspection, identify the actual PostgreSQL role used by the backend. Do not disclose the connection string.
- [ ] Confirm the deployed candidate includes the startup guard that queries `current_user` and rejects `anon`/`authenticated`; this guard is a fail-closed defence, not a substitute for private Render role inspection.
- [ ] Confirm Render uses a direct server-side PostgreSQL connection as a trusted backend role, not `anon`, `authenticated`, or an untrusted Data API path.
- [ ] Verify all objects requiring least privilege are owned/created by the expected migration role. Migration 0004 default privileges cover future objects created by `postgres`; other object-creating roles need a separate grant audit.
- [ ] Confirm the candidate's Supabase bearer-token authentication and owner-scoped API checks match the live grants/RLS design. Do not assume candidate migrations or simulated tenancy tests have been applied or verified in production; prove the Render role, schema revision and two-account isolation first.
- [ ] Confirm Render blueprint settings and cost tier before any sync/deploy. Candidate blueprint is configured for the existing service name and Free plan; verify live service configuration rather than assuming it synced.

## Secret rotation

Rotate the API key that was previously exposed. Generate a new random value of at least 32 characters in a password manager. Update privately:
- Render environment variable `API_KEY`
- GitHub Actions secret `MF_TERMINAL_API_KEY`

Also verify GitHub Actions secret `MF_TERMINAL_API_URL` contains the service base URL without a trailing slash. Never copy secret values into this runbook or chat.

## Database migration execution

Only after all pre-deployment checks and explicit release approval:
1. Confirm the intended Render service is connected to the authorised branch/commit.
2. Deploy the exact candidate SHA.
3. Confirm Render's start command runs `alembic upgrade head` before Uvicorn.
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
- [ ] Run the official AMFI live-source validation workflow.
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
