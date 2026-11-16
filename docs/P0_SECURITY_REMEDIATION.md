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

## Latest known live Supabase evidence

The latest read-only audit available in this work context found:

- One confirmed Supabase Auth user at the inspected checkpoint.
- Zero portfolios and zero distinct portfolio owners at that checkpoint.
- One portfolio goal linked to the confirmed user; it had no portfolio link and was not orphaned. Do not delete or reassign it.
- Eleven internal tables had RLS enabled and denied direct `anon`/`authenticated` SELECT access.
- Supabase Security Advisor reported the leaked-password-protection setting disabled and informational RLS-enabled/no-policy findings on deny-all internal tables. Health Advisor had no findings. Performance Advisor listed unused-index informational notices; do not drop indexes automatically.
- The actual Render PostgreSQL connection role and deployed application SHA remained unverified.

These observations are timestamped evidence, not a live guarantee. Refresh them before release. The lack of two separately owned portfolios means a real two-account production isolation test has not been demonstrated.

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
- [ ] Verify the actual Render database role and deployed SHA privately.
- [ ] Confirm the candidate migration chain and production drift have no unexplained differences.
- [ ] Configure required GitHub Actions secrets without disclosing values.
- [ ] Complete real signup, confirmation, login, session, password-reset and sign-out browser tests.
- [ ] Complete two-account production/staging isolation evidence using approved test accounts.
- [ ] Complete encrypted off-site backup and isolated restore drill.
- [ ] Complete live AMFI refresh, idempotent replay, correction provenance and data freshness checks.
- [ ] Complete portfolio workflow E2E and append-only ledger checks.
- [ ] Complete approved Render deployment smoke tests and rollback evidence.

## Safety and release boundary

This document does not authorise a production migration, deployment, test-account creation, portfolio mutation or destructive action. Keep production inspection read-only until the exact candidate SHA, migration diff, actual database role, successful backup/restore and explicit release approval are all present.

See [P0 Execution and Evidence Matrix](P0_EXECUTION_MATRIX.md) for gate-by-gate acceptance criteria and the [Final Release Runbook](FINAL_RELEASE_RUNBOOK.md) for the controlled release procedure.
