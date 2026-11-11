# Development Roadmap — MF Terminal Intelligence

Last updated: 2026-11-11
Authorised working branch: audit/production-foundation
Repository: yashvyas638/mf-terminal-intelligence-backend
Governance: DEVELOP → TEST → REVIEW → COMMIT → PUSH → VERIFY CI → SUPABASE → RENDER → PRODUCTION TEST → PHASE SIGN-OFF.

## Release controls
- main is protected from this work; do not merge without explicit approval.
- Never reset, truncate, drop, or destructively alter production data without explicit approval.
- Never place credentials, connection strings, API keys, or secret-bearing logs in this file, commits, screenshots, or reports.
- A phase is COMPLETE only when its exit criteria have evidence. Otherwise mark it BLOCKED or PARTIALLY COMPLETE.
- Record exact commit SHAs, CI evidence, migration revisions, deployment identifiers, smoke-test results, limitations, and rollback reference for each release.
- GitHub branch metadata cannot establish local working-tree cleanliness; a local git status check is required.

## Phase status
| Phase | Scope | Status | Exit condition |
|---|---|---|---|
| P0 | Infrastructure, reliability, data integrity, production readiness | OPEN — BLOCKED | All P0 gates below verified |
| P1 | Universal portfolio import, scheme/fund master, official fund documents and metadata | NOT STARTED | P0 signed off |
| P2 | Performance, risk, benchmark and rolling analytics | NOT STARTED | P1 signed off |
| P3 | Holdings, sector, overlap, concentration and portfolio risk | NOT STARTED | P2 signed off |
| P4 | Macro, rates, inflation, currency, global markets and stress regimes | NOT STARTED | P3 signed off |
| P5 | Decision framework, scoring, allocation, tax and opportunity-cost analysis | NOT STARTED | P4 signed off |
| P6 | Wealth projections, goals, tax, snapshots and monitoring | NOT STARTED | P5 signed off |
| P7 | Source-linked AI research, assistant and exports | NOT STARTED | P6 signed off |
| P8 | Full regression, security, isolation, performance, recovery and UX QA | NOT STARTED | P7 signed off |

## P0 exit checklist and evidence
| Gate | Status | Current evidence / blocker |
|---|---|---|
| Confirm authorised remote branch and exact head | VERIFIED | GitHub remote ref refs/heads/audit/production-foundation points to 3ca12c92a717da5bdda79911e793483d6a376ac9 on 2026-11-11. |
| Verify local working tree clean | NOT VERIFIED | No local checkout/status capability used. A local git status --short result is still required. |
| Inspect complete Supabase schema, migrations, indexes, constraints and RLS | PARTIAL / BLOCKED | Repository ORM metadata and both Alembic revisions inspected. Live Supabase catalog and RLS policies have not been queried. |
| PostgreSQL compatibility independent of SQLite CI | NOT VERIFIED | Existing CI runs Alembic and tests on SQLite only. A PostgreSQL integration run against disposable/staging PostgreSQL is required; do not use production for destructive tests. |
| Live AMFI response and parser validation | PARTIAL / BLOCKED | Configured URL is https://portal.amfiindia.com/spages/NAVAll.txt. A web-opened copy was semicolon-delimited and showed the expected six-column header, but retrieval metadata reported three months old. This is not a fresh live fetch from the service runtime. |
| Validate records before database insertion | PARTIAL | Code parses and applies a minimum valid-record threshold before writes. Need live payload evidence and stronger quality checks for date/freshness and source-format drift. |
| Duplicate and missing-ISIN handling | PARTIAL | Parser tests cover duplicate scheme/date rows and '-' ISIN normalization. Database upsert behavior and live-feed cases still need integration tests. |
| Historical NAV preservation | BLOCKED / RISK FOUND | Unique key is scheme/date. Existing rows for a matching date are overwritten on re-ingestion; this may be intended for official corrections but is not immutable history. Daily NAVAll feed alone is not a historical backfill. Define and test correction provenance and preservation policy. |
| Render deployment commit | NOT VERIFIED | Desired SHA is 3ca12c92a717da5bdda79911e793483d6a376ac9; Render deployment record has not been inspected. |
| Supabase PostgreSQL live connectivity and migration state | NOT VERIFIED | No authenticated live database catalog or Alembic current-revision evidence available. |
| End-to-end AMFI → backend → Supabase → dashboard/portfolio | NOT VERIFIED | Public Render health endpoint could not be retrieved by the available web reader; authenticated API and dashboard workflow not exercised. |
| FastAPI startup deprecation | REVIEW REQUIRED | app/main.py uses deprecated @app.on_event('startup') for init_db(). Lifespan is the supported replacement. Migration is likely safe if startup behavior is preserved, but should be a separately tested code change after confirming migration/bootstrap responsibilities. |
| Rollback commit and procedure | PARTIAL / BLOCKED | Candidate code commit is known; last known-good production deployment commit and deploy ID are not verified. Do not label a code commit as production-good without Render evidence. |

## Code-level observations requiring P0 resolution
1. app/db.py defines schemes, ingestion snapshots, NAV observations, portfolios, transactions, and transaction audit records. It defines a unique constraint on (scheme_code, nav_date), plus indexes for NAV scheme/date, portfolio transaction date/scheme, and transaction audit lookup.
2. The two checked-in migrations are 0001_schema_baseline and 0002_portfolio_ledger_audit. The baseline adopts Base.metadata.create_all; migration 0002 adds void columns and an audit table/index. Their actual state on Supabase is unknown.
3. The inspected portfolio schema has no owner/user/tenant column or equivalent ownership mapping. API-key authentication is service-wide, not per-user portfolio isolation. Do not expose this backend as a multi-user service until explicit ownership and authorization design is implemented and tested.
4. No RLS policies are defined in the inspected application migrations. Live Supabase RLS state must be inspected; do not assume RLS is enabled or disabled from application code alone.
5. init_db() calls Base.metadata.create_all at application startup in addition to Alembic migrations in the Render start command. Review this dual schema-management path and keep migrations authoritative.
6. render.yaml in this commit declares a Starter plan, while the previously observed service was described as Free. Verify actual Render service configuration; repository blueprint text is not proof of live service configuration.
7. The dashboard contains NAV search/refresh and portfolio controls, but complete end-to-end behavior and ownership safeguards are not verified.

## Rollback record
- Candidate reviewed source commit: 3ca12c92a717da5bdda79911e793483d6a376ac9.
- Last known-good production commit: UNKNOWN — must be obtained from Render deployment history.
- Last known-good Render deploy ID/timestamp: UNKNOWN.
- Rollback procedure: use Render deployment history to redeploy the exact previously successful deployment/commit; verify /health, authenticated NAV status, and dashboard read paths. Do not run a database downgrade as part of application rollback. If a release included a schema migration, use a reviewed forward-fix or verified backup restore plan; never assume a code rollback reverses a migration.
- Before any release, record the prior successful Render deploy ID, commit SHA, timestamp, and current Alembic revision here.

## P0 evidence log
### 2026-11-11 — repository and code review
- Remote branch ref confirmed at 3ca12c92a717da5bdda79911e793483d6a376ac9.
- Prior CI run for this SHA: run ID 43020514070, job 130522253718; SQLite migration, Ruff F,B, and pytest passed; pytest reported 15 passed and 3 warnings.
- CI does not prove PostgreSQL compatibility, Supabase connectivity, RLS, Render deployment, live AMFI ingestion, or end-to-end production behavior.
- No local working-tree status, production database mutation, or production deployment was performed during this review.