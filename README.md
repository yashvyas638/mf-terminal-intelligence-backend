# MF Terminal Intelligence — NAV Data Service

A deployable FastAPI service that retrieves the official AMFI all-schemes NAV feed, validates it, and stores dated NAV observations plus append-only correction provenance in PostgreSQL (production) or SQLite (local tests only).

> Research support only. This service does not place orders, provide investment advice, or reconcile a scheme against AMC disclosures.

## What it does

- Protects `/v1/*` data endpoints with a verified Supabase Auth session or a server-side operator API key; NAV refresh remains restricted to the server-side operator key.
- Downloads AMFI's official `NAVAll.txt` source only when an authenticated refresh is requested.
- Rejects empty, malformed, oversized, invalid-UTF-8, stale, and unexpectedly small source responses before changing persisted data.
- Stores scheme metadata, dated NAV observations, source hashes, quality metrics, and validation details.
- Preserves prior NAV values and both source snapshot references when AMFI republishes a corrected NAV for the same scheme/date.
- Uses Alembic as the production schema manager; production startup does not run ORM create-all.
- Prevents duplicate refreshes within a process and across PostgreSQL-backed service instances using an advisory lock.
- Provides health, freshness, scheme search, history, and latest-snapshot endpoints.
- Records an append-only audit event for each portfolio transaction and supports audited voids rather than destructive deletes.
- Rejects transaction cash/NAV mismatches and any transaction or void that would create a negative unit balance.
- Includes GitHub Actions CI and a Monday–Saturday 09:30 IST scheduler.

## Quick start

Python 3.12.16 is the pinned and CI-tested runtime.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
export API_KEY='replace-with-a-long-random-secret'
# Optional for local SQLite; production must set DATABASE_URL to PostgreSQL.
export ENVIRONMENT=development
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Check the service at `http://127.0.0.1:8000/health`; interactive API documentation is at `/docs`.

```bash
curl -X POST http://127.0.0.1:8000/v1/nav/refresh \
  -H "X-API-Key: $API_KEY"
```

The production safety threshold is `MINIMUM_VALID_RECORDS=1000`. Lower it only for controlled testing; do not set it to zero in production.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Public database/service readiness probe with a validated Render deployment commit fingerprint; exposes no secrets or portfolio data. |
| `POST /v1/nav/refresh` | Downloads, validates, and persists a new AMFI snapshot; server-side operator key only. |
| `GET /v1/nav/status` | Latest ingestion snapshot and retrieval freshness. |
| `GET /v1/nav/schemes?q=&limit=&offset=` | Paginated scheme search with latest stored NAV. |
| `GET /v1/nav/schemes/{scheme_code}` | Scheme metadata, ISINs, latest stored NAV, observation coverage and NAV-derived metrics. |
| `POST /v1/analytics/compare` | Compare 2–10 schemes on stored AMFI NAV series; each scheme's coverage is reported independently. |
| `GET /v1/nav/history/{scheme_code}?days=` | Stored NAV history for one scheme. |
| `GET /v1/nav/snapshot/latest` | Latest full validation report. |
| `POST /v1/portfolios` | Creates a portfolio owned by the authenticated Supabase user (or trusted server-side operator). |
| `GET /v1/portfolios` | Lists only the signed-in user's portfolios; operator access is server-side only. |
| `POST /v1/portfolios/{id}/transactions` | Creates a validated BUY/SELL ledger transaction. |
| `POST /v1/portfolios/{id}/transactions/{transaction_id}/void` | Audited void; never deletes a financial record. |
| `GET /v1/portfolios/{id}/transactions/{transaction_id}/audit` | Immutable, authenticated event history for one transaction. |
| `POST /v1/portfolios/{id}/transactions/import/preview` | Validates a CSV without writing transactions and returns a short-lived signed confirmation token. |
| `POST /v1/portfolios/{id}/transactions/import` | Requires the preview token; atomically imports the exact normalized statement and rejects duplicates. |
| `POST /v1/portfolios/{id}/rebalance/preview` | Non-executable target-allocation trade estimate using stored NAVs. |
| `GET /v1/portfolios/{id}/valuation` | Latest stored-NAV valuation, with explicit missing-coverage status. |

**Authentication rules**

- Browser/user access to `/v1/*` requires `Authorization: Bearer <Supabase access token>`; the backend verifies the token against Supabase Auth and scopes portfolio access to the verified user ID.
- Trusted scheduled/server automation uses `X-API-Key`; the key must remain in server-side secret storage and must never be embedded in browser JavaScript, HTML, mobile apps, or committed files.
- `POST /v1/nav/refresh` is deliberately excluded from browser-session auth and requires the server-side operator key.
- `GET /health` is public and reports only service/database readiness, not portfolio or account data.
- Supabase RLS and table grants provide database-layer defence in depth. Application ownership checks also apply to portfolio reads, writes, imports, audit history, valuation and rebalance previews.

## Deployment on Render

1. Push this folder to a GitHub repository.
2. Create a managed PostgreSQL database. Do **not** use SQLite on an ephemeral web-service disk in production.
3. Create a Render Web Service using `render.yaml`, and set `DATABASE_URL` to the private PostgreSQL runtime URL. Production mode rejects SQLite.
4. Configure `MIGRATION_DATABASE_URL` separately as a private, direct-session PostgreSQL connection for Alembic only. It must not equal `DATABASE_URL`; the Procfile/blueprint unsets it before Uvicorn starts. Never expose this credential to application requests or browser code.
5. Keep Render's generated `API_KEY`, or replace it with a strong secret of at least 32 characters.
6. Verify the actual Render service start command matches `render.yaml`; a committed blueprint does not prove the existing dashboard service has been synced. Confirm `/health` reports `database: reachable`, then run one authenticated refresh.
7. Add `MF_TERMINAL_API_URL` and `MF_TERMINAL_API_KEY` as GitHub Actions secrets. The included scheduler refreshes Monday–Saturday at 22:45 IST, after AMFI's normal publication window (including late liquid/overnight NAVs).

**Migration privilege warning:** Revision `0029_admin_default_acl` requires the migration identity to alter default privileges for every role that can create objects in the `public` schema. A standard Supabase `postgres` connection may not be authorised to manage `supabase_admin` defaults. If the migration preflight rejects the role, stop and use a Supabase-supported privileged migration path; do not weaken or bypass the check. Do not assume that configuring the URL alone makes production migrations safe.

### Release checklist

- Run `alembic upgrade head` against a staging copy and confirm the recorded revision before promoting a release.
- Store `API_KEY`, `DATABASE_URL`, and scheduler credentials only in the deployment secret manager; never commit a populated `.env` file.
- Trigger one authenticated NAV refresh, then verify `/v1/nav/status` reports the expected retrieval timestamp and quality status.
- Configure an external probe for `/health` and alert on failed refresh jobs or `STALE_RETRIEVAL` data.
- Restore a PostgreSQL backup into a non-production environment and run the migration and API smoke checks before relying on disaster recovery.

## Quality and operational boundaries

Run checks locally with:

```bash
ruff check --select F,B .
pytest -q
```

NAV refresh uses a process-local fast guard plus a PostgreSQL session-level advisory lock across service instances. SQLite tests exercise only the local guard; the PostgreSQL CI job exercises the database lock.

Alembic is the sole production schema manager. The reviewed Render blueprint runs `alembic upgrade head` before starting the API and removes `MIGRATION_DATABASE_URL` from the Uvicorn process environment. Verify the actual Render dashboard command after every service/blueprint change; the dashboard configuration can differ from the committed YAML. `init_db()` remains only for local development and isolated tests. Production application startup does not create or mutate schema.

## Portfolio ledger integrity

Portfolio transactions are immutable financial facts. To correct one, use the audited void endpoint with a reason and record a replacement transaction; do not alter rows directly. The API enforces `amount = units × NAV` rounded to paisa and evaluates the complete dated ledger before accepting a BUY, SELL, or void, so an oversell cannot be stored.

`valuation_status=PARTIAL_MISSING_NAV` means at least one active holding has no stored NAV. In that state the displayed covered holding values are informational only: aggregate unrealized gain/loss, total gain/loss, and XIRR are intentionally withheld rather than calculated from incomplete coverage.

## Statement import and rebalancing

The statement-import workflow accepts CSV text with a header and these required fields (common aliases shown): `date`/`transaction_date`, `scheme_code`, `type`/`transaction_type`, `units`, `nav`, and `amount`; `charges` and `notes` are optional. Preview validates known schemes, arithmetic and chronological unit balances without writing transactions. The confirmation token is bound to the portfolio, normalized transaction fingerprint and row count, and expires after 10 minutes. Confirmation revalidates under a per-portfolio database lock and commits all rows atomically. Re-importing the same normalized statement into the same portfolio is rejected. The raw statement is deliberately not retained; only a SHA-256 fingerprint is stored.

The rebalance preview accepts target percentages totaling exactly 100 and returns indicative BUY/SELL/HOLD quantities at the latest stored NAV. It rejects stale NAV inputs rather than presenting them as current values. It does not consider taxes, exit loads, scheme restrictions, or suitability, and never executes transactions.


### NAV ingestion performance and resilience

The refresh pipeline streams the official AMFI file with a 30 MB hard cap, bounded connect/read timeouts, and up to three attempts for transient network/HTTP failures. It records response metadata (status, content type, bytes and attempt number) without logging payloads or credentials. A failed or malformed source response never replaces accepted data.

Persistence uses batched scheme and NAV lookups rather than one database round-trip per feed row. The validated snapshot, scheme-master changes, NAV observations and correction history are committed in one transaction. Exact replays remain idempotent; corrections retain their prior-value provenance.

The candidate NAV-refresh workflow is scheduled for 22:45 IST Monday–Saturday to avoid racing AMFI's evening publication. It is not active in production while it exists only on `audit/production-foundation`: GitHub scheduled workflows run from the default branch, and the current `main` branch has no NAV-refresh workflow or Render Cron service. Activate it only through an approved release or a separately approved production scheduler. Manual refresh remains available when the operator key is configured. AMFI's official NAVAll.txt remains the sole ingestion authority; third-party mirrors are not silently substituted into the canonical dataset.

## NAV correction history

The current NAV table stores one effective value per scheme/date. If AMFI republishes a different value for the same date, the previous value, replacement value, both source snapshot IDs, and correction timestamp are appended to `nav_observation_revisions` before the effective observation is updated. Replaying an identical feed does not create a correction record. This preserves corrections observed after migration 0003; it cannot reconstruct values overwritten before that migration.

## Authentication and tenancy boundary

- Browser users authenticate with Supabase email/password and send a verified Supabase access token as a bearer token. The API resolves the token through Supabase Auth, rejects users without `email_confirmed_at`, and scopes portfolio operations to the authenticated user.
- Portfolio ownership checks cover portfolio reads/writes, transaction history, imports, audit history, valuation, goals and rebalance previews. PostgreSQL RLS and grants are intended as defence in depth; their live production posture must be checked against the current migration chain and actual Render database role before release.
- Runtime PostgreSQL access uses `DATABASE_URL`; API startup rejects PostgreSQL superuser credentials. Production Alembic migrations require a separate privileged `MIGRATION_DATABASE_URL`, which the startup command unsets before launching the API process.
- The server-side operator API key remains restricted to trusted automation and operator endpoints such as NAV refresh. It is never a browser-user identity and must not be embedded in frontend assets.
- Simulated two-user tests and SQLite/PostgreSQL CI are necessary but do not prove live cross-account isolation. P0 remains blocked until two real confirmed Supabase accounts, separately owned test portfolios and browser/API negative-access tests demonstrate isolation.
- Fund comparison currently uses stored AMFI NAV series for 2–10 schemes. Its metrics are NAV-derived; it does not by itself provide benchmark TRI, distribution-adjusted total returns or peer/category ranking.
- Never expose the service as a public multi-user product until live Auth, database-role, grants/RLS, browser workflows and two-account isolation evidence are recorded. Keep all credentials in secret stores; use a strong operator key and rotate any previously exposed value.

## Database and source CI

CI applies migrations and runs tests independently against SQLite and PostgreSQL 16, including financial CHECK constraints, append-only audit triggers, import idempotency and advisory locking. A separate scheduled/manual workflow validates the public AMFI response without writing to any database. These checks do not replace verification against the actual Supabase project or Render deployment.


## Product roadmap and engineering governance

The product is developed in seven gated phases. Read these documents before changing scope:

- [Development Roadmap — phase gates and acceptance criteria](DEVELOPMENT_ROADMAP.md)
- [Product Blueprint — modules, user outcomes and feature boundaries](docs/PRODUCT_BLUEPRINT.md)
- [Engineering Playbook — end-to-end development, CI, database and deployment flow](docs/ENGINEERING_PLAYBOOK.md)
- [Architecture and Data Model — canonical entities, tenancy and provenance](docs/ARCHITECTURE_AND_DATA_MODEL.md)
- [UX and Design System — terminal experience and interaction standards](docs/UX_AND_DESIGN_SYSTEM.md)
- [Final Release Runbook — Supabase, Render, smoke tests and rollback](docs/FINAL_RELEASE_RUNBOOK.md)

**Current phase: P0 — OPEN / BLOCKED.** Application-level Supabase bearer authentication, ownership checks, database hardening migrations and simulated two-user tests exist on this candidate branch. This is not production sign-off: live Auth/browser flows, real two-account isolation, actual Render database role and deployed SHA, production grants/RLS, encrypted off-site backup plus isolated restore, live AMFI ingestion and full endpoint smoke tests remain evidence gates. Track each gate in [P0 Execution and Evidence Matrix](docs/P0_EXECUTION_MATRIX.md). P1 analytics must not be represented as complete until its benchmark/peer dependencies and acceptance tests pass. Do not merge to `main`, deploy or perform destructive production operations without explicit approval and a verified recovery plan.


## P0 security remediation

Historical Supabase access findings, current candidate controls and remaining live-verification requirements are tracked in [P0 Security Remediation](docs/P0_SECURITY_REMEDIATION.md) and the [P0 Execution and Evidence Matrix](docs/P0_EXECUTION_MATRIX.md). The production database was last observed at revision `0028_restrictive_private_access`; the candidate branch adds `0029_admin_default_acl` and separate migration-credential handling. Reconcile the complete candidate migration chain with the live schema and verify the privileged migration role, runtime database role, backup/restore and exact deployed SHA before any approved release.


## NAV ingestion diagnostics

The service emits structured lifecycle diagnostics for refresh start, source HTTP metadata, validation totals, freshness/minimum-record gates, database transaction failures and successful snapshot commits. Logs exclude API keys, database URLs and raw feed contents. `GET /health` confirms only basic database connectivity; use authenticated `GET /v1/nav/status` and the snapshot ID/quality details to verify actual ingestion.


### Historical NAV backfill (operator-only, gated)

AMFI's official NAV Download page documents a maximum 90-day date range per history download. The backfill planner therefore keeps the hard 90-day validation limit but defaults to conservative 7-day windows to bound response size and make retries/resume granular. The planner is idempotent and makes no network requests; each window has a durable checkpoint. A bounded worker batch can be resumed after a timeout or process restart. Historical fetching remains disabled unless both `AMFI_HISTORY_CONTRACT_VERIFIED=true` and `AMFI_HISTORY_BACKFILL_ENABLED=true` are explicitly configured after a live source-contract check.

- `POST /v1/nav/backfill/plan` — create checkpoints (default 7-day windows; configurable up to 90 days), no AMFI request.
- `GET /v1/nav/backfill/status` — inspect pending/running/failed/complete windows and inserted/corrected/unchanged totals.
- `POST /v1/nav/backfill/run` — run a bounded batch only after both release gates are enabled; operator key required.

Do not enable the execution gates solely because CI passes. First verify a live response from the official AMFI NAV History form for each scheme type and reconcile its response dates and row layout. The public AMFI page confirms the 90-day maximum: https://www.amfiindia.com/net-asset-value/nav-download.
