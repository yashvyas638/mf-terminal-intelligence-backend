# P0 Security Remediation — Supabase, tenancy and database boundary

Last reconciled: 2026-11-16  
Candidate branch: `audit/production-foundation`  
Production rule: no migration or deployment without explicit release approval.

## Executive status

P0 remains **OPEN — BLOCKED**. The candidate application has moved beyond the original shared-operator-only design: it implements Supabase bearer-token validation, owner-scoped portfolio operations, database hardening migrations and simulated two-user tests. These are code-level controls, not proof that the currently deployed Render service and live Supabase database enforce the same boundary.

The old statements in this document that the service has no authenticated user identity or portfolio ownership model describe an earlier architecture and must not be used as the current candidate-branch description.

## Historical finding — 2026-11-11 to 2026-11-12

An earlier read-only review reported RLS disabled on the then-inspected public tables. Effective privilege checks at that checkpoint did not confirm direct `anon` or `authenticated` table access; SQL Editor's `current_user = postgres` did not establish the Render service's database role. That report is retained as historical context, not as a current live-state assertion.

The observed production Alembic revision at the later 2026-11-12 checkpoint was `0007_append_only_audit`. The candidate branch has since advanced. Production and candidate schema must therefore be reconciled before any migration or deployment.

## Candidate-branch security controls

The current candidate architecture includes:

- Supabase email/password authentication in the dashboard and Research Terminal.
- Backend bearer-token verification against Supabase Auth `/auth/v1/user`.
- Owner-scoped portfolio access and checks across portfolio reads/writes, transactions, imports, audit history, valuation and rebalance workflows.
- Portfolio-goal ownership checks, including validation that a linked portfolio belongs to the same user as the goal.
- A production startup guard that identifies PostgreSQL `current_user` and rejects untrusted `anon` or `authenticated` database identities.
- Alembic migrations for client-role containment, ownership, financial constraints, append-only evidence and research/security tuning.
- SQLite and PostgreSQL CI plus simulated cross-user isolation tests.

Do not infer live deployment or migration status from these source-code controls.

## Latest live Supabase evidence — 2026-11-16 09:51 UTC (read-only)

Project `zgfdvhzhvccsfmpoaqah` was inspected using read-only SQL, table metadata and Supabase advisors. No DDL or data mutation was executed.

- `public.alembic_version` reports `0028_restrictive_private_access`. The Supabase MCP migration-list endpoint returned no rows because the application uses Alembic; the Alembic version table is the relevant application migration record.
- Data counts: 16,143 schemes, 2,664,820 NAV observations, 317 ingestion snapshots, 34,852 research snapshots and 1,092 backfill checkpoints. Portfolio and transaction tables are empty; one portfolio goal exists.
- One confirmed Auth user exists. The goal belongs to a confirmed user; there are no goals linked to a portfolio owned by another user and no unconfirmed goal owner. There are no portfolios, so real two-account isolation remains untested.
- RLS is enabled on all 21 inspected public tables. Effective table privileges show no `anon` access. `authenticated` has SELECT only on the six intended read surfaces; it has no write privileges.
- All 18 inspected public sequences deny `anon` and `authenticated` USAGE/SELECT. The two public financial trigger functions are SECURITY INVOKER, have fixed `search_path=pg_catalog, public`, and deny EXECUTE to `anon` and `authenticated`.
- Eleven RLS-enabled tables have no policies and are denied direct client privileges; this matches the intended backend-only model and explains the informational advisor notices.
- **New P0 finding:** effective defaults for `postgres`, `pg_database_owner` and `supabase_admin` include PostgreSQL's built-in `PUBLIC EXECUTE` for future functions; `supabase_admin` also has explicit schema-specific grants to `anon` and `authenticated` for future public tables, sequences and functions. Existing public functions are currently owned by `postgres` and deny client execution; the risk concerns future objects. Candidate migration `0029_admin_default_acl` revokes global and `public`-schema PUBLIC/client defaults for tables, sequences and functions for every role able to CREATE in `public`; the P0 audit evaluates the effective combination of global and schema-specific defaults. Production is not changed by this candidate migration. The inspected SQL role `postgres` is not a member of `supabase_admin`, so it cannot be assumed to apply this migration; the migration fails closed unless its connection is authorised for every creator role.
- Security Advisor reports one warning: native leaked-password protection disabled; 11 informational RLS-enabled/no-policy notices. Health Advisor reports no findings. Performance Advisor reports 24 unused-index INFO notices; do not drop these automatically.
- The SQL inspection connection reports `current_user=postgres`. This is not evidence of the actual Render backend connection role.

The browser-side Pwned Passwords range check remains a mitigation only; it is not equivalent to native server-side leaked-password protection.


## Migration and database controls

Migrations are forward-only where they protect financial evidence or security posture. Never run a downgrade merely to roll back application code.

Before applying any candidate migration to production:

1. Fetch the exact candidate branch SHA and ordered Alembic migration chain.
2. Compare all tables, columns, indexes, constraints, triggers, policies, grants, sequences, functions and ownership against live Supabase.
3. Confirm the actual Render database role privately. Never paste `DATABASE_URL`, connection strings or credentials into chat or logs.
4. Verify the role is a trusted server-side database role and not `anon` or `authenticated`.
5. Verify direct client grants and RLS policy behaviour for every public table, including inherited PUBLIC privileges and default privileges.
6. Verify security-definer functions have a fixed safe `search_path` and least-privilege EXECUTE grants.
7. Take a fresh encrypted off-site backup and complete a restore into a separate isolated project.
8. Obtain explicit release approval before deployment or migration.

The migration head in the release evidence must be read from the candidate and approved deployment; do not hard-code an old revision such as `0007_append_only_audit`.

## Two-account isolation acceptance test

Use two real, confirmed test accounts with no production financial data:

- Account A creates portfolio A and goal A.
- Account B creates portfolio B and goal B.
- A must not list, read, update, import into, void, audit, value, rebalance or infer B's records by changing IDs or request parameters.
- B must not access A's records.
- A goal linked to a portfolio owned by the other account must be rejected.
- Invalid, expired, missing and malformed bearer tokens must be rejected.
- Sign-out and fresh sign-in must not leak the previous account's cached UI state.
- Repeat key negative tests through direct API requests, not only by hiding UI controls.

Record redacted request/result evidence, account labels (A/B, never email/password), timestamp, environment and exact deployed SHA. Do not create these accounts or test records in production without an approved test plan and explicit permission.

## Credential and provider controls

- Rotate any operator key previously exposed in chat, screenshots or logs.
- Store operator/API/database credentials only in Render and GitHub Actions secret stores.
- Do not expose the operator key to browser JavaScript, HTML, mobile apps or repository files.
- Verify Supabase Email provider, Site URL, redirect allow-list and SMTP delivery in a real browser.
- Supabase Free tier may not expose native leaked-password protection. The browser-side Pwned Passwords range check is a mitigation only; it is not equivalent to a server-side Auth control and can be bypassed by direct Auth API calls.

## Remaining P0 work

- [ ] Refresh live Supabase schema, grants, RLS, functions and migration revision evidence.
- [ ] Apply candidate migration `0029_admin_default_acl` only after CI, Render role and backup/restore approval; verify no unsafe effective future-object default ACLs remain.
- [ ] Confirm the migration connection is superuser/member of every public-schema creator role; otherwise execute through an approved privileged migration path.
- [ ] Verify the actual Render database role and deployed SHA privately.
- [ ] Confirm the candidate migration chain and production drift have no unexplained differences.
- [ ] Configure required GitHub Actions secrets without disclosing values.
- [ ] Complete real signup, confirmation, login, session, password-reset and sign-out browser tests.
- [ ] Enable native leaked-password protection where supported, or record explicit risk acceptance and compensating controls; frontend breach screening is not equivalent.
- [ ] Complete two-account production/staging isolation evidence using approved test accounts.
- [ ] Complete encrypted off-site backup and isolated restore drill.
- [ ] Complete live AMFI refresh, idempotent replay, correction provenance and data freshness checks.
- [ ] Complete portfolio workflow E2E and append-only ledger checks.
- [ ] Complete approved Render deployment smoke tests and rollback evidence.

## Safety and release boundary

This document does not authorise a production migration, deployment, test-account creation, portfolio mutation or destructive action. Keep production inspection read-only until the exact candidate SHA, migration diff, actual database role, successful backup/restore and explicit release approval are all present.

See [P0 Execution and Evidence Matrix](P0_EXECUTION_MATRIX.md) for gate-by-gate acceptance criteria and the [Final Release Runbook](FINAL_RELEASE_RUNBOOK.md) for the controlled release procedure.
