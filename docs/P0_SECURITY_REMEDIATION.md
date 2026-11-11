# P0 Security Remediation — Supabase client-role containment

## Live finding (2026-11-11)

The production `public` schema contains eight application tables. RLS was
reported disabled on all eight and `pg_policies` returned no policies.
`information_schema.role_table_grants` showed table privileges assigned to
Supabase API roles `anon` and `authenticated`. SQL Editor reported
`current_user = postgres`; this does not establish Render's connection role.

The schema has no portfolio owner/tenant column. The current FastAPI service
uses a shared server-side API key and is a trusted single-operator/private
workspace design, not a multi-user SaaS authorization model.

## Migration 0004

`0004_restrict_supabase_client_roles` revokes existing table, sequence and
function privileges from `anon` and `authenticated`, and revokes their
default privileges for future objects created by PostgreSQL role `postgres`.

This is containment, not a substitute for RLS or per-user authorization. It
does not modify, delete, rewrite or truncate application data. The downgrade
is deliberately a no-op so a code rollback cannot silently reopen access.
CI creates Supabase-role fixtures and tests that the roles cannot access
application tables after migration.

## Portfolio import integrity addition (migration 0005)

Migration `0005_portfolio_import_dedup` adds a per-portfolio statement fingerprint ledger. The service stores only the SHA-256 fingerprint, import timestamp and row count—not raw CSV statement content. Re-uploading the exact same CSV to the same portfolio is rejected with HTTP 409. This prevents accidental duplicate ledger entries; it is not a substitute for row-level reconciliation when the same transactions appear in a differently formatted statement.

## Production precondition

Before applying migration 0004 in production, verify Render's
`DATABASE_URL` uses a trusted server-side PostgreSQL role, not `anon` or
`authenticated`. Never paste connection strings or credentials into chat,
GitHub issues or logs. If Render uses Supabase Data API rather than direct
PostgreSQL, stop and redesign the access path before deployment.

## Remaining P0 work

- Verify Render's actual database connection role without exposing secrets.
- Verify Supabase Data API cannot read or mutate application tables as
  `anon` or `authenticated` after migration.
- For multi-user use, add authenticated identity, owner/tenant columns,
  approved ownership backfill, ownership checks in every service query, RLS
  policies and cross-user isolation tests.
- Audit objects created by roles other than `postgres`.
- Rotate any API key previously exposed in chat/screenshots and update Render
  and GitHub Actions secret stores without disclosing values.
- Verify production migration, health, NAV persistence, portfolio flows,
  backups and rollback before P0 sign-off.

## Safety

The migration changes permissions only. It does not touch portfolio
transactions, NAV observations, source snapshots, correction history or
scheme master data. Do not merge to `main` or deploy until the exact SHA,
CI and Render connection role are verified and the user approves.
