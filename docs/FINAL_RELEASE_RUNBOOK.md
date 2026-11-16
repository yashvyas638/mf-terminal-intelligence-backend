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

The candidate code migration head is `0007_append_only_audit`.

1. `0001_schema_baseline` — adopts/creates the original application schema.
2. `0002_portfolio_ledger_audit` — portfolio audit and void fields.
3. `0003_nav_correction_history` — append-only NAV correction provenance.
4. `0004_supabase_role_lockdown` — revokes table/sequence/function grants from Supabase `anon` and `authenticated` roles; no production execution until the Render DB role is verified.
5. `0005_portfolio_import_dedup` — per-portfolio normalized statement fingerprints.
6. `0006_ledger_db_constraints` — preflights existing rows, then adds financial CHECK constraints.
7. `0007_append_only_audit` — prevents UPDATE/DELETE on portfolio audit and NAV correction history.

The migrations are forward-only for financial evidence: downgrades deliberately do not remove audit/provenance or restore broad client privileges. Rollback is normally an application-code redeploy plus forward-fix, not an Alembic downgrade.

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
- [ ] Confirm RLS and API grants intentionally match the single-operator architecture. Do not enable multi-user exposure: portfolio ownership/JWT/RLS is not implemented.
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
5. Query the database privately and verify `alembic_version.version_num = '0007_append_only_audit'`.
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
