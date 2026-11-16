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

`0004_supabase_role_lockdown` revokes existing table, sequence and
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
### Code-level startup defence (2026-11-12)

The production lifespan now queries PostgreSQL `current_user` and refuses to start when the connection identity is `anon` or `authenticated`. It allows a trusted server-side role and fails closed if the role cannot be identified. Automated tests cover both rejected client roles and an accepted server-side role. Verified on commit `cac21e0e4daba3680e2bee99481e93b099d83031`; CI run `43142960810` passed SQLite and PostgreSQL jobs.

This does **not** prove which role the live Render service currently uses. The private Render environment must still be inspected before migration 0004 or any production deployment.


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

## Connected Supabase verification (2026-11-12, read-only)

Project mf-terminal-intelligence was inspected using read-only project/table/advisor queries and SQL SELECT statements. No DDL, data mutation or production migration was executed.

Observed:
- Alembic database revision: 0007_append_only_audit.
- Data present: 14,206 schemes, 22,305 NAV observations and 4 ingestion snapshots; portfolio and transaction tables are currently empty.
- RLS is disabled on all 9 public tables, and there are no RLS policies.
- Effective privilege checks (has_table_privilege) returned false for both anon and authenticated on SELECT and INSERT for every public table. The expanded table ACL check also found no PUBLIC table grants. service_role has the expected server-side table privileges.
- SQL Editor reports current_user = postgres. This is not evidence of the Render backend connection identity; Render remains unverified.
- The schemes table does not yet have research classification columns.
- Supabase security advisor flags prevent_financial_audit_mutation() for a mutable search_path. A safe function-search-path hardening migration is being added to the synchronized research branch; it has not been applied to production.

Interpretation:
- The RLS-disabled finding is a critical hardening gap and must be resolved deliberately. However, the direct privilege checks did not confirm that anon or authenticated currently have table SELECT/INSERT access. Do not describe this as confirmed anonymous table access.
- Enabling RLS without policies could block access for roles that do not bypass RLS. Design and test the intended server-side role path and any future user policies before changing production.
- Re-run grants, RLS, policy, sequence and function checks after the approved permission migration.
