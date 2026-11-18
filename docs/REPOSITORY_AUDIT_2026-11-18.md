# Repository audit — 18 November 2026

## Scope and evidence

This review covers the active application branch, deployment configuration, migration chain, static asset references, operational workflows, and live Supabase/Render state. It is an evidence-based audit, not a claim that every application behavior has been manually exercised against production data.

- Audited application baseline: `dace3178d2cf8e4bd1753886cfad5ecc51aa857b`
- Latest green CI on that baseline: [run 44290194934](https://github.com/yashvyas638/mf-terminal-intelligence-backend/actions/runs/44290194934)
- Render service: `mf-terminal-intelligence-backend`
- Supabase project: `mf-terminal-intelligence`

## Confirmed healthy

- SQLite and PostgreSQL CI suites pass.
- Ruff, frontend JavaScript syntax/security tests, DOM contract checks, and operational workflow validation pass.
- Four read-only AMFI source/taxonomy checks pass.
- Supabase project reports `ACTIVE_HEALTHY`.
- The live NAV unique constraint/index remains in place; the duplicate non-unique NAV lookup index was removed previously without deleting NAV observations.
- Live client grants show no `anon` table grants. The `authenticated` role has SELECT only on the six intended read surfaces: schemes, NAV observations, portfolios, portfolio transactions, portfolio transaction audit, and import batches.
- The UI's CSS/JavaScript assets are referenced by the current HTML pages. In particular, terminal-ui v5/v6 are used by Research Terminal and must not be treated as dead files.

## Fixes in this audit branch

- Aligned `Procfile` with `render.yaml`: run Alembic using the migration-only connection, unset `MIGRATION_DATABASE_URL`, then start Uvicorn.
- Added operational workflow validation so CI checks that the Procfile and Render blueprint startup commands match.
- Added a CI guard requiring all three Supabase backup dumps to use the documented `--db-url` flag and reject the unsupported `--remote` connection-string usage.
- Repaired two literal escaped line breaks in the README API table.

## Production blockers — not marked as fixed

### Render

The live Render service configuration still reports the older start command:

```bash
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

The repository blueprint includes `unset MIGRATION_DATABASE_URL` before Uvicorn, but the actual service configuration has not been synced to that blueprint. The latest deployment attempt failed during Alembic startup because `MIGRATION_DATABASE_URL` was not configured. The previous successful deployment remains the live release. No Render environment secret or service setting was changed by this audit.

### Supabase migrations

- Live Alembic revision remains `0028_restrictive_private_access`.
- Candidate repository head is `0030_remove_duplicate_nav_index`.
- Revision 0029 deliberately fails closed unless the migration identity can alter default privileges for every role with CREATE on `public`. The current inspected `postgres` identity cannot manage `supabase_admin` defaults.
- Do not bypass this check, grant unsupported role membership, or apply 0030 independently.
- No production Alembic migration was applied during this audit.
- The Supabase CLI migration-history listing and Alembic's `public.alembic_version` are separate migration systems; do not treat a Supabase CLI migration record as proof that the Alembic chain advanced.

### Backup and recovery

- The encrypted backup workflow now uses the documented Supabase CLI `--db-url` option.
- The latest backup workflow run stopped at configuration validation because required GitHub Actions secrets are missing. No export or upload was attempted.
- There is no verified automated off-site backup or restore drill yet. Do not describe backup as operational until an end-to-end run and isolated restore both pass.

### Security advisor

- Supabase reports 11 RLS-enabled backend tables without policies. These are not automatically dead or public: current table-grant inspection shows no direct `anon` grants. Keep them backend-only and re-check grants/policies whenever schema changes.
- Supabase Auth's native leaked-password protection is disabled. Enable it in Auth settings when available; the browser-side screening is not equivalent to native server-side enforcement.
- The unused-index advisor findings are not deletion instructions. Validate index workload and query plans before removing any additional index.

### TWT / portfolio live-data validation

The live database previously had no portfolios or verified holdings disclosures. Therefore report regression tests do not prove a genuine production-data TWT report. Market-cap look-through also remains dependent on a verified security-level classification source.

## Cleanup decisions

No CSS or JavaScript asset was deleted because every current static asset is referenced by a page. No FastAPI route handler was removed: route functions are invoked by FastAPI decorators and are false positives for simple text-reference dead-code scans. No index was dropped from production as part of this review.

## Release gates

1. Configure a supported, separate migration connection in Render through the private secret settings; do not paste credentials into source control or chat.
2. Confirm the actual Render start command matches the reviewed blueprint and that the app health check reports the intended commit.
3. Establish the encrypted backup secrets, run the backup workflow, and complete an isolated restore test.
4. Obtain an approved Supabase migration identity that satisfies revision 0029, then take/verify a backup before applying revisions 0029 and 0030.
5. Seed verified portfolio and holdings data in a non-production environment and complete TWT end-to-end validation.
6. Re-run CI, Render health, Supabase advisors, and data-integrity checks before calling the repository production-ready.
