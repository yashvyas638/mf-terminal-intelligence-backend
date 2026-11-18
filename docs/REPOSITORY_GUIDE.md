# MF Terminal Intelligence — Repository Guide

Last reviewed: 2026-11-18
Repository: `yashvyas638/mf-terminal-intelligence-backend`
Working integration branch: `ui/portfolio-intelligence`
Default branch: `main`

## 1. Purpose and source of truth

This repository contains the FastAPI backend and its browser-served terminal assets. It is the home for the API, ingestion, analytics, portfolio ledger, authentication/authorization, database migrations, tests, deployment workflows and engineering documentation.

Use the default branch only as the currently published baseline. Feature branches and pull requests may contain unreleased work. A branch name or green CI run is not proof that code is deployed to Render or that a production migration has run.

Before each change, record:
- repository and working branch;
- exact base and head commit SHAs;
- PR number/state and whether it is mergeable;
- relevant schema migration head;
- required checks on the exact candidate SHA;
- production deployed SHA and migration revision, where verified.

Never infer local working-tree cleanliness from GitHub. Never reset, force-push, delete branches or rewrite shared history as routine cleanup.

## 2. System architecture

Logical request/data path:

```text
Browser terminal
  ├─ Supabase Auth JS client (email/password, session persistence/refresh)
  ├─ Public Supabase publishable key (browser-safe identifier)
  └─ API calls with Authorization: Bearer <Supabase access token>
          |
          v
FastAPI application (Render)
  ├─ resolve and verify bearer token with Supabase Auth
  ├─ derive the user ID from verified Auth response (never trust a browser-supplied owner ID)
  ├─ enforce owner-scoped application checks on private portfolio operations
  ├─ operator-only routes additionally require server-side X-API-Key
  └─ SQLAlchemy -> PostgreSQL/Supabase using trusted server-side DATABASE_URL
          |
          v
PostgreSQL
  ├─ Alembic-managed schema
  ├─ owner identifiers and constraints
  ├─ RLS + least-privilege grants
  ├─ append-only financial/audit provenance
  └─ shared reference data (schemes/NAV/research inputs)

GitHub Actions
  ├─ CI: SQLite + PostgreSQL + migrations + lint + JS/contract checks
  ├─ scheduled/manual AMFI and operational checks
  └─ operator API requests via GitHub Secrets

Render
  ├─ serves FastAPI app
  ├─ secrets configured in service environment
  └─ deployment SHA must be verified independently
```

## 3. Authentication and credential handling

### Browser user session

1. User signs up or signs in through Supabase Auth.
2. The Supabase browser client receives a session containing an access token and refresh token.
3. The browser client is configured with `persistSession`, `autoRefreshToken` and `detectSessionInUrl`.
4. Frontend API wrappers attach `Authorization: Bearer <access_token>`.
5. FastAPI sends the bearer token to the configured Supabase Auth user endpoint and derives the authenticated user ID from the verified response.
6. Portfolio records are filtered/checked against that user ID. Database RLS and grants form an additional boundary.
7. On sign-out/account change, private workspace state and in-flight request responses must be invalidated so an old account's data cannot repopulate the new account's view.

The Supabase publishable key is intended to be browser-visible. It is not a user password, access token, refresh token, database password or service-role secret. Keep service-role credentials and database URLs server-side only.

### Operator/service authentication

`X-API-Key` is a shared server-side operator credential for trusted automation and restricted operations such as NAV ingestion/refresh. Store it in Render environment variables and GitHub Actions Secrets. Never put it into static HTML/JS, browser localStorage/sessionStorage, source control, issue comments or logs.

A shared API key is not an identity system and must not grant ordinary users access to personal portfolio data. User portfolio routes require a verified Supabase identity. NAV refresh remains operator-only.

### Other credentials/tokens

- `DATABASE_URL`: trusted runtime PostgreSQL connection, server-side only.
- `MIGRATION_DATABASE_URL`: separate privileged migration connection where configured; do not expose to the running web process or browser.
- Supabase service-role/secret keys: server-side only; never use as the browser publishable key.
- Statement-import confirmation token: short-lived, bound to a specific portfolio and normalized import fingerprint/row count; not a login token.
- GitHub Actions secrets: available only to workflow runtime; never echo values.
- Public `/health`: returns service/database readiness only, never personal data or secret material.

## 4. Repository map

| Path | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI routes, auth dependencies, API contracts, portfolio operations |
| `app/db.py` | SQLAlchemy models, engine/session setup |
| `app/nav_ingest.py` | AMFI NAV source parsing/validation |
| `app/*_history*` | Historical NAV source, planning, persistence and worker logic |
| `app/analytics.py` and related modules | Deterministic research/portfolio metrics |
| `app/static/` | Browser terminal HTML, JavaScript and CSS |
| `migrations/versions/` | Ordered Alembic schema/security/data migrations |
| `tests/` | Unit, integration, migration, API, security and frontend contract tests |
| `.github/workflows/` | CI, scheduled ingestion, backup and production audits |
| `scripts/` | Repeatable audit and operational validation tools |
| `docs/` | Product/technical specs, security, operations and release evidence |
| `DEVELOPMENT_ROADMAP.md` | Phase gates and acceptance criteria |
| `render.yaml`, `Procfile` | Render service configuration |
| `requirements.lock` / `requirements.txt` | Locked/runtime Python dependencies |

Do not create parallel copies of the same application or migrations. Keep one canonical version of each technical contract.

## 5. Development workflow

Mandatory sequence:

```text
DEFINE scope and phase
  -> INSPECT current branch, code, schema and deployment
  -> DESIGN contracts, risks and rollback
  -> DEVELOP a small coherent change
  -> TEST unit + integration + PostgreSQL + migrations + UI
  -> REVIEW complete diff, secrets and backwards compatibility
  -> COMMIT on the authorised feature branch
  -> PUSH and verify exact remote SHA
  -> CI green on that exact SHA
  -> STAGING migration and data reconciliation
  -> explicit production release approval
  -> deploy approved SHA
  -> smoke test + monitor + record evidence
```

Useful local checks (after installing the locked dependencies):

```bash
python -m pip install -r requirements.lock
ruff check .
pytest -q
node --check app/static/dashboard.js
node --check app/static/research.js
node --check app/static/fund-detail.js
alembic upgrade head
```

For migrations, test both a fresh database and the previous supported revision against PostgreSQL. SQLite is useful but does not prove PostgreSQL RLS, grants, advisory locks or production compatibility.

## 6. Database and data integrity rules

- Alembic is the production schema authority; do not use ORM `create_all` to mutate production.
- Never run destructive migrations, truncate, reset or bulk rewrite production data without explicit approval and verified restorable backup.
- User-owned records require an owner key and application authorization. A guessed ID is never authorization.
- Keep monetary and NAV calculations in Decimal/NUMERIC, preserve effective dates and source provenance.
- Financial transaction corrections must be audited/voided rather than silently overwritten or deleted.
- Never fabricate missing NAV, ISIN, benchmark, category or holdings data. Surface gaps and source/as-of dates.
- Use idempotency and unique constraints for ingestion/import paths.
- Keep private portfolio tables inaccessible to anonymous/authenticated direct clients unless an explicitly reviewed policy requires otherwise.

## 7. Current release status — reviewed 2026-11-18

This is a repository review, not a claim that production has been verified.

### Confirmed from GitHub

- Open PR #135: Allocation and look-through Portfolio Intelligence UI. Its latest reported CI run (#1965) passed SQLite, PostgreSQL and live read-only AMFI source validation on the candidate SHA.
- PR #135 explicitly states that no production migration, production data write, secret change, Render deployment or trade execution has been performed.
- PR #135 also records limitations: no real production holdings disclosures imported by that PR; market-cap classification is operator-imported/manual; allocation target-gap preview is not yet fund-level Smart SIP routing; tax-aware, sector/security, liquidity and risk-budget constraints remain future work.
- Open PR #1: audit/production foundation. GitHub reports it open and not mergeable at the time of review. It contains a large integration/release foundation and must be reconciled deliberately, not merged blindly.
- Other open PRs include #112, #87, #79, #70, #46, #7 and #4. Triage each against current `main` and the active integration branch; close only after confirming its change is either merged elsewhere or intentionally superseded.
- The development roadmap on the candidate branch describes P0 as OPEN/BLOCKED. Do not mark it complete based on CI alone.

### Production evidence still required

1. Verify Render's actual deployed commit SHA and service logs.
2. Verify runtime DB role and migration DB role without disclosing connection details.
3. Reconcile live Supabase schema, migration revision, grants and RLS with the candidate migration chain.
4. Confirm a current, restorable backup and test restore into a non-production project.
5. Verify two real, separately confirmed Supabase users cannot read or mutate each other's portfolio/goal/watchlist/report data.
6. Verify live AMFI refresh, persisted snapshot, current NAV effective date and dashboard readback.
7. Verify scheduled workflows are enabled on the default branch and have successful recent executions.
8. Import/reconcile real holdings disclosures and confirm their as-of dates, coverage and verification status before using them for portfolio overlap/look-through outputs.
9. Complete a browser-level auth lifecycle check: sign-up, confirmation, sign-in, refresh, password recovery, sign-out, second-account switch, stale-request invalidation and private state reset.
10. Complete production smoke tests and record rollback/recovery evidence.

## 8. Work prioritisation

P0 — Release/security/data foundation:
- Branch and PR integration hygiene.
- Exact deployed SHA and configuration verification.
- Runtime/migration DB-role separation and secret rotation where needed.
- Live RLS/grant and two-account isolation evidence.
- Backup/restore proof.
- AMFI freshness, history coverage, data quality and refresh scheduling.
- Portfolio ledger/import correctness and operational monitoring.

P1 — Fund research:
- Performance windows and fair data baselines.
- Benchmark TRI alignment and category/peer comparability.
- Source evidence and stale/missing data states.

P2 — Exposure research:
- Verified holdings coverage, overlap and concentration.
- Market-cap/sector exposure with provenance.
- Distinguish holdings overlap from return correlation.

P3–P6 — Macro/stress, optimisation/decision centre, tax/wealth/reporting, AI research and production hardening. Do not skip upstream evidence gates.

## 9. Branch and PR policy

- `main` is the production/release baseline.
- Use one authorised integration branch for coordinated feature development; use short-lived branches for isolated fixes.
- Avoid stacking duplicate feature branches or maintaining parallel implementation histories.
- Rebase/merge `main` into an integration branch only after recording both SHAs and resolving conflicts with tests.
- PRs must state phase, scope, acceptance criteria, schema/security impact, test evidence, deployment status and remaining limitations.
- Do not merge because CI is green alone. Require code review, migration/data review and release evidence.
- Protect `main` with required CI and review once the repository configuration has been reviewed and agreed.

## 10. Important limits of this guide

This guide records source-code and GitHub evidence visible during the review. It does not claim access to Render environment variables/logs, Supabase production records, the user's local working tree, browser session storage or live account credentials. Those require separate authenticated operational checks.
