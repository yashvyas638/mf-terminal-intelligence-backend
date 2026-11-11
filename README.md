# MF Terminal Intelligence — NAV Data Service

A deployable FastAPI service that retrieves the official AMFI all-schemes NAV feed, validates it, and stores dated NAV observations plus append-only correction provenance in PostgreSQL (production) or SQLite (local tests only).

> Research support only. This service does not place orders, provide investment advice, or reconcile a scheme against AMC disclosures.

## What it does

- Protects every data endpoint with a constant-time API-key check.
- Downloads AMFI's official `NAVAll.txt` source only when an authenticated refresh is requested.
- Rejects empty, malformed, and unexpectedly small source responses before changing persisted data.
- Stores scheme metadata, dated NAV observations, source hashes, quality metrics, and validation details.\n- Preserves prior NAV values and both source snapshot references when AMFI republishes a corrected NAV for the same scheme/date.\n- Uses Alembic as the production schema manager; production startup does not run ORM create-all.
- Prevents duplicate refreshes within a running service process.
- Provides health, freshness, scheme search, history, and latest-snapshot endpoints.
- Records an append-only audit event for each portfolio transaction and supports audited voids rather than destructive deletes.
- Rejects transaction cash/NAV mismatches and any transaction or void that would create a negative unit balance.
- Includes GitHub Actions CI and a Monday–Saturday 09:30 IST scheduler.

## Quick start

Python 3.11+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set a strong API_KEY in .env, then export it for your shell.
export API_KEY='replace-with-a-long-random-secret'
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
| `GET /health` | Public database/service readiness probe; exposes no data or secrets. |
| `POST /v1/nav/refresh` | Downloads, validates, and persists a new AMFI snapshot. |
| `GET /v1/nav/status` | Latest ingestion snapshot and retrieval freshness. |
| `GET /v1/nav/schemes?q=&limit=&offset=` | Paginated scheme search with latest stored NAV. |
| `GET /v1/nav/history/{scheme_code}?days=` | Stored NAV history for one scheme. |
| `GET /v1/nav/snapshot/latest` | Latest full validation report. |
| `POST /v1/portfolios/{id}/transactions` | Creates a validated BUY/SELL ledger transaction. |
| `POST /v1/portfolios/{id}/transactions/{transaction_id}/void` | Audited void; never deletes a financial record. |
| `GET /v1/portfolios/{id}/transactions/{transaction_id}/audit` | Immutable, authenticated event history for one transaction. |
| `POST /v1/portfolios/{id}/transactions/import` | Atomic CSV statement import with validation and no raw-statement retention. |
| `POST /v1/portfolios/{id}/rebalance/preview` | Non-executable target-allocation trade estimate using stored NAVs. |
| `GET /v1/portfolios/{id}/valuation` | Latest stored-NAV valuation, with explicit missing-coverage status. |

Except `/health`, every endpoint requires `X-API-Key`.

## Deployment on Render

1. Push this folder to a GitHub repository.
2. Create a managed PostgreSQL database. Do **not** use SQLite on an ephemeral web-service disk in production.
3. Create a Render Web Service using `render.yaml`, and set `DATABASE_URL` to the private PostgreSQL URL. Production mode rejects SQLite.
4. Keep Render's generated `API_KEY`, or replace it with a strong secret.
5. Confirm `/health` reports `database: reachable`, then run one authenticated refresh.
6. Add `MF_TERMINAL_API_URL` and `MF_TERMINAL_API_KEY` as GitHub Actions secrets. The included scheduler then refreshes Monday–Saturday at 09:30 IST.

### Release checklist

- Run `alembic upgrade head` against a staging copy and confirm the recorded revision before promoting a release.
- Store `API_KEY`, `DATABASE_URL`, and scheduler credentials only in the deployment secret manager; never commit a populated `.env` file.
- Trigger one authenticated NAV refresh, then verify `/v1/nav/status` reports the expected retrieval timestamp and quality status.
- Configure an external probe for `/health` and alert on failed refresh jobs or `STALE_RETRIEVAL` data.
- Restore a PostgreSQL backup into a non-production environment and run the migration and API smoke checks before relying on disaster recovery.

## Quality and operational boundaries

Run checks locally with:

```bash
ruff check .
pytest -q
```

The included concurrency guard applies to a single process. If this service is scaled to multiple workers or instances, use a PostgreSQL advisory lock or a dedicated job queue before enabling more than one scheduler.

Alembic is the sole production schema manager. Render runs `alembic upgrade head` before starting the API. `init_db()` remains only for local development and isolated tests. Production startup does not mutate schema.

## Portfolio ledger integrity

Portfolio transactions are immutable financial facts. To correct one, use the audited void endpoint with a reason and record a replacement transaction; do not alter rows directly. The API enforces `amount = units × NAV` rounded to paisa and evaluates the complete dated ledger before accepting a BUY, SELL, or void, so an oversell cannot be stored.

`valuation_status=PARTIAL_MISSING_NAV` means at least one active holding has no stored NAV. In that state the displayed covered holding values are informational only: aggregate unrealized gain/loss, total gain/loss, and XIRR are intentionally withheld rather than calculated from incomplete coverage.

## Statement import and rebalancing

The statement-import endpoint accepts CSV text with a header and these required fields (common aliases shown): `date`/`transaction_date`, `scheme_code`, `type`/`transaction_type`, `units`, `nav`, and `amount`; `charges` and `notes` are optional. It rejects unknown scheme codes, invalid arithmetic, invalid dated ledgers, and files above 5,000 rows. Imports are all-or-nothing. The raw statement is deliberately not retained; only a SHA-256 fingerprint is included in the transaction audit event.

The rebalance preview accepts target percentages totaling exactly 100 and returns indicative BUY/SELL/HOLD quantities at the latest stored NAV. It does not consider taxes, exit loads, scheme restrictions, or suitability, and never executes transactions.

## NAV correction history

The current NAV table stores one effective value per scheme/date. If AMFI republishes a different value for the same date, the previous value, replacement value, both source snapshot IDs, and correction timestamp are appended to `nav_observation_revisions` before the effective observation is updated. Replaying an identical feed does not create a correction record. This preserves corrections observed after migration 0003; it cannot reconstruct values overwritten before that migration.

## Authentication and tenancy boundary

The current service uses one shared server-side API key and is suitable only for a single trusted operator/private workspace. It is not yet a multi-tenant public SaaS: portfolio records are not bound to authenticated user identities, and the shared API key is not a substitute for per-user JWT authorization and Supabase RLS. Do not expose it to unrelated users until ownership mapping, authorization checks, and RLS have been implemented and verified. Use a random API key of at least 32 characters.

## Database and source CI

CI applies migrations and runs tests independently against SQLite and PostgreSQL 16. A separate scheduled/manual workflow validates the public AMFI response without writing to any database. These checks do not replace verification against the actual Supabase project or Render deployment.
