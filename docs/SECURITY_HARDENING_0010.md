# Security hardening — migration 0010

## Status
Proposed migration for review. It has **not** been applied to production.

## Why this follows migration 0009
The live Alembic head is `0009_audit_function_search_path`. This migration is
numbered `0010_rls_hardening` and explicitly depends on that revision. The
older uploaded proposal named 0008 and must not be used.

## Behaviour
- Preflight checks the migration connection role before changing anything.
  It aborts unless that role is a superuser, has BYPASSRLS, or owns every
  ordinary/partitioned table in public.
- Enables RLS (not FORCE RLS) on every ordinary/partitioned public table.
- Revokes all table, sequence and function privileges from `anon`,
  `authenticated`, and `PUBLIC`.
- Revokes matching default privileges for objects created by the role running
  this migration.
- Reasserts fixed search_path on both financial audit trigger functions.
- Downgrade is intentionally a no-op. Rollback is a deliberate operational
  action after diagnosing the connection role and access requirements.

## Important limitations
- This is a private backend-only design. It creates no end-user RLS policies.
  Do not expose these tables through Supabase client APIs.
- Default privileges are per object-creating role. If another role creates
  objects in public, its default ACLs need a separate review.
- The preflight checks the migration role, not automatically the Render runtime
  role. The runtime role must independently be verified with the read-only
  checker against the exact Render DATABASE_URL before release.
- This migration has not yet been run against a restored staging copy or
  production. Do not merge/deploy until backup restore, runtime-role proof,
  PostgreSQL integration tests, API smoke tests and postflight checks pass.

## Release gate
1. Take a production backup and restore it into a separate scratch/staging DB.
2. Run the read-only security checker using the exact runtime DATABASE_URL
   against staging; never disclose the URL.
3. Run migrations and API smoke tests on staging.
4. Verify RLS flags, table/sequence/function ACLs, role privileges, trigger
   behaviour, `/health`, and authenticated `/v1/nav/schemes`.
5. Only then approve production deployment in a maintenance window.
