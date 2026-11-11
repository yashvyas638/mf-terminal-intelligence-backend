# Engineering Playbook — End-to-End Delivery

## Non-negotiable branch and release policy

- Work only on the authorised branch: audit/production-foundation, until explicitly changed.
- Never push feature work to main and never merge the existing PR without explicit approval.
- GitHub remote is the source of truth.
- Before editing: inspect branch head, current file content, open PR state and relevant tests.
- Never overwrite a file based on stale content SHA. Fetch latest content immediately before update.
- One logical change per commit where practical.
- Never claim a clean local tree unless local git status was actually run.
- Never expose secrets in code, commits, issue comments, logs, screenshots or reports.

## Standard development cycle

1. **DEFINE:** identify phase, user outcome, scope, non-goals, dependencies and acceptance criteria.
2. **INSPECT:** read affected code, schema, migrations, tests, configuration, current branch and deployment state.
3. **DESIGN:** document data flow, failure modes, security implications, migration/rollback and observability.
4. **DEVELOP:** implement the smallest coherent change; preserve existing contracts unless versioned.
5. **TEST:** run formatting/lint, unit tests, integration tests, PostgreSQL tests, migration tests and relevant UI/API tests.
6. **REVIEW:** inspect complete diff for correctness, security, privacy, performance, compatibility and accidental scope.
7. **COMMIT:** descriptive commit message; no secrets or generated junk.
8. **PUSH:** push only to authorised branch.
9. **VERIFY CI:** wait for all required checks on the exact pushed SHA; inspect logs and test counts.
10. **DATABASE:** inspect target environment and migration current revision; use backup/staging for rehearsal; never destructive-test production.
11. **DEPLOY:** confirm intended Render service, environment, deployed SHA and migration output.
12. **SMOKE TEST:** health, auth, data endpoints, dashboard, portfolio read/write in an approved test scope, background jobs.
13. **RECORD:** update DEVELOPMENT_ROADMAP.md and release evidence.
14. **SIGN OFF:** report pass/fail per acceptance criterion; phase remains open if any critical gate is unverified.

## Change risk classes

- **R0 Documentation:** no runtime effect. Still require markdown/link review.
- **R1 Isolated code:** no schema change and no financial data mutation; full unit/regression tests.
- **R2 Schema additive:** new nullable column/table/index; migration reviewed, PostgreSQL CI and staging rehearsal, backup confirmation.
- **R3 Data migration/backfill:** explicit mapping, dry run, counts/checksums, idempotency, batch strategy, pause/abort, rollback/forward-fix plan and user approval.
- **R4 Destructive or irreversible:** DROP, truncate, reset, rewrite, delete, production overwrite. Prohibited without explicit user approval and verified recovery plan.

## Required CI matrix

- Python supported-version check (at least pinned production runtime).
- Ruff lint and formatting.
- Unit tests.
- SQLite migration and tests for fast developer feedback.
- PostgreSQL service integration job using the same PostgreSQL major version as production.
- Alembic upgrade from empty database and from prior supported revision.
- Migration idempotency/revision check.
- API contract and auth tests.
- Parser fixtures: valid, empty, HTML, malformed, duplicate, missing identifier, future date, stale date, extreme count, invalid numeric.
- NAV persistence: first insert, exact replay, official correction, transaction rollback on failure.
- Portfolio import: preview, validation, duplicate detection, reconciliation, partial row errors, all-or-nothing commit.
- Frontend build/static checks and browser smoke tests when UI changes.
- Security dependency scan and secret scan.

A passing SQLite job never substitutes for PostgreSQL integration.

## Database and migration discipline

- PostgreSQL is the production source of truth; SQLite is local/test convenience only.
- Alembic is the only production schema-change mechanism.
- Production application startup must not run create_all or silently modify schema.
- Migration must be reviewed for lock duration, table rewrite, nullability, indexes, foreign keys and backwards compatibility.
- Prefer expand → migrate/backfill → validate → contract over breaking in-place changes.
- Every migration must define a safe downgrade or explicitly state why downgrade is intentionally non-destructive/unsupported.
- Never run downgrade against production as a routine rollback.
- Record current revision before and after deployment.
- Verify backup availability and restore procedure before risky migrations.

## Data pipeline contract

Source → fetch → raw response metadata/hash → parse → schema validation → quality gate → normalise → stage → persist transactionally → reconciliation → publish freshness → dashboard/API.

Reject before write:
- empty or unexpectedly small payload
- HTML/error page or content-type mismatch
- parser failure or unsupported format
- duplicate identity conflicts not safely resolved
- invalid/non-finite/negative NAV
- invalid dates or future-dated observations
- unacceptable stale data
- record-count or coverage anomalies
- source checksum already processed when no new information exists (record replay, do not duplicate)

Persist:
- source URL and source name
- retrieved_at UTC and source effective date
- payload hash and parser version
- valid/invalid/duplicate counts
- quality status and sampled issues
- source snapshot ID on every observation
- corrections as append-only revision events

Publish only after transaction commit and post-write reconciliation. Failed ingestion must leave previously accepted data available.

## Portfolio import contract

1. Upload file securely with size/type limits.
2. Parse to a preview; do not persist.
3. Normalise scheme identifiers and transaction types.
4. Validate required columns, dates, units, NAV, amount, charges and arithmetic.
5. Detect duplicate rows and probable duplicate statements; show warnings.
6. Resolve unmatched schemes; never guess ambiguous matches.
7. Show imported, skipped, rejected and unresolved rows.
8. Reconcile row count, units and value totals with source statement.
9. User confirms import.
10. Persist atomically with source fingerprint and audit events.
11. Recompute holdings and valuation; show exceptions and missing NAV.
12. Provide downloadable import result/reconciliation.

Do not retain raw statements unless retention is explicitly justified and secured. Do not silently discard rejected rows.

## API and security contract

- Use versioned routes (/v1) and explicit request/response schemas.
- Use short-lived/user-scoped auth for multi-user product; service API key is only for trusted service-to-service calls.
- Every portfolio query must be scoped to authenticated owner/tenant.
- RLS must enforce least-privilege access where Supabase is used; application authorization remains mandatory.
- Never trust a portfolio_id supplied by client without ownership check.
- Rate-limit refresh/import and expensive analytics.
- Keep secrets in Render/GitHub secret stores; rotate exposed secrets.
- Redact authorization headers, connection strings, tokens, statements and personal financial data from logs.
- Use parameterized SQL/ORM; no LLM-generated write SQL.
- CORS allowlist, secure headers, request size limits, timeouts and dependency patching.
- Health endpoint reveals no secret/config values. Separate liveness from readiness if needed.

## NAV correctness rules

- Canonical scheme identity is scheme code plus validated ISIN metadata; ISIN can be missing and must not be fabricated.
- Missing ISIN in a later feed does not erase a previously confirmed ISIN; record the source state.
- One current observation per scheme/date; every official correction creates an immutable revision with previous/new values and source snapshots.
- Exact replay must be idempotent.
- Duplicate scheme/date in one feed must be resolved deterministically and counted.
- NAV values use Decimal, never binary float for persistence/calculation.
- No synthetic NAV rows or interpolated values.
- NAV effective date and retrieval timestamp are separate.
- Stale/missing NAV must be visible in valuation and analysis.
- A daily feed does not prove long-term historical completeness.

## Render deployment checklist

Before deploy:
- exact feature branch SHA and CI pass
- correct service and environment confirmed
- environment variable names and non-secret metadata verified
- DATABASE_URL points to PostgreSQL, never SQLite
- API key length/rotation and GitHub scheduler secret sync checked without displaying values
- backup and migration plan reviewed
- prior known-good deploy ID/SHA recorded

After deploy:
- deployment reports intended commit SHA
- build/start logs show successful migration revision and server startup
- /health reports database reachable
- unauthenticated protected endpoint returns 401
- authenticated status endpoint returns expected response
- dashboard HTML/static assets load
- NAV status, scheme search, NAV history and portfolio valuation work
- no secret leakage in logs
- scheduled job and manual trigger behave as expected
- observe error rate and data freshness

## Rollback

- Roll back application to the exact last known-good Render deployment, not a guessed commit.
- Verify health, database reachability, auth and core read endpoints.
- Do not downgrade schema automatically.
- For additive backward-compatible migrations, old application code should continue to run.
- For incompatible migrations, use forward-fix or approved restore plan.
- Preserve failed deployment logs with secrets redacted.
- Record incident, cause, impact, rollback SHA/deploy ID and follow-up tests.

## Phase sign-off template

- Phase and scope:
- Feature branch and exact commit SHA:
- Changed files:
- Tests and exact outcomes:
- PostgreSQL/migration evidence:
- Supabase revision/schema/RLS evidence:
- Render deployment ID and deployed SHA:
- Production smoke tests:
- Data reconciliation and freshness:
- Security/privacy review:
- Known limitations and blockers:
- Rollback target and recovery evidence:
- Status: COMPLETE / PARTIALLY COMPLETE / BLOCKED:
- Next phase approval requested: YES / NO

No phase is COMPLETE on code review alone.
