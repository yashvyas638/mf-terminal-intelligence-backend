# MF Terminal Intelligence — NAV Data Service

A secure, deployable FastAPI service that retrieves the official AMFI all-schemes NAV feed, validates it, and stores an auditable daily history in SQLite (local development) or PostgreSQL (production).

> Research support only. This service does not place orders, provide investment advice, or reconcile a scheme against AMC disclosures.

## What it does

- Protects every data endpoint with a constant-time API-key check.
- Downloads AMFI's official `NAVAll.txt` source only when an authenticated refresh is requested.
- Rejects empty, malformed, and unexpectedly small source responses before changing persisted data.
- Stores scheme metadata, dated NAV observations, source hashes, quality metrics, and validation details.
- Prevents duplicate refreshes within a running service process.
- Provides health, freshness, scheme search, history, and latest-snapshot endpoints.
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

Except `/health`, every endpoint requires `X-API-Key`.

## Deployment on Render

1. Push this folder to a GitHub repository.
2. Create a managed PostgreSQL database. Do **not** use SQLite on an ephemeral web-service disk in production.
3. Create a Render Web Service using `render.yaml`, and set `DATABASE_URL` to the private PostgreSQL URL.
4. Keep Render's generated `API_KEY`, or replace it with a strong secret.
5. Confirm `/health` reports `database: reachable`, then run one authenticated refresh.
6. Add `MF_TERMINAL_API_URL` and `MF_TERMINAL_API_KEY` as GitHub Actions secrets. The included scheduler then refreshes Monday–Saturday at 09:30 IST.

## Quality and operational boundaries

Run checks locally with:

```bash
ruff check .
pytest -q
```

The included concurrency guard applies to a single process. If this service is scaled to multiple workers or instances, use a PostgreSQL advisory lock or a dedicated job queue before enabling more than one scheduler.

Alembic manages versioned schema changes. The baseline safely adopts tables created by the earlier `create_all` bootstrap; run `alembic upgrade head` before deploying each schema release. Application startup retains `create_all` as a backwards-compatible bootstrap, not as a replacement for reviewed migrations.
