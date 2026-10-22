# MF Terminal Intelligence — Cloud NAV Foundation (Phase 1)

This is the first deployable backend layer for the existing private MF Terminal Intelligence plugin. It is not a duplicate plugin. It is a separate API service that can later be connected to the existing plugin through a supported API/MCP integration.

## What this phase implements

- Fetches the official AMFI all-schemes NAV text file (`https://www.amfiindia.com/spages/NAVAll.txt`) on an authenticated refresh request.
- Parses semicolon-delimited scheme rows; validates positive numeric NAVs, scheme codes, names, and dates.
- Stores scheme master, dated NAV observations, and an auditable ingestion snapshot in SQLAlchemy-compatible SQLite or PostgreSQL.
- Stores source URL, retrieval time, payload SHA-256, min/max NAV dates, row counts, warnings and validation report.
- Provides protected API endpoints for refresh, status, scheme search, NAV history, and latest snapshot.
- Includes a GitHub Actions scheduled workflow (runs Monday–Saturday at 09:30 IST by default) that calls the refresh endpoint after secrets are configured.
- Includes automated parser tests with a synthetic fixture.

## Important limitations

- This service has not been deployed to a cloud provider from this workspace.
- The AMFI endpoint has not been live-tested from this build environment. The first deployed refresh is the live acceptance test.
- It does not yet reconcile each scheme against AMC pages, ingest full historic NAV backfill, reconcile merged/renamed scheme identities, or provide benchmark/holdings/factsheet data.
- It does not yet connect the ChatGPT plugin to this API. The existing plugin is a private workflow plugin; the API/MCP integration is a separate follow-on task.
- It is research support only and does not execute transactions.

## Run the tests locally

Python 3.11+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\\Scripts\\activate     # Windows PowerShell
pip install -r requirements.txt
pytest -q
```

Expected: four parser tests pass. Tests use a small synthetic sample, not a live AMFI download.

## Run locally

```bash
export DATABASE_URL='sqlite:///./mf_terminal.db'
export API_KEY='replace-with-a-long-random-secret'
uvicorn app.main:app --reload --port 8000
```

Then open `http://127.0.0.1:8000/docs` for interactive API documentation and `http://127.0.0.1:8000/health` for the health check.

Refresh data (requires the API key):

```bash
curl -X POST http://127.0.0.1:8000/v1/nav/refresh -H 'X-API-Key: replace-with-a-long-random-secret'
```

## Cloud deployment architecture

Recommended first deployment for a non-developer: **Render web service + managed PostgreSQL + GitHub Actions schedule**. This keeps the database persistent and the scheduled refresh independent of the web service's uptime. Provider pricing and free-tier availability change; review the provider's current pricing before creating paid resources.

1. Create a private GitHub repository and upload these files.
2. Create a PostgreSQL database in your chosen cloud provider. Copy its internal connection URL; keep it private.
3. Create a Render Web Service from the GitHub repository. Build command: `pip install -r requirements.txt`. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
4. Add environment variables `DATABASE_URL` (managed PostgreSQL URL) and `API_KEY` (a long random secret). Do not commit secrets to GitHub.
5. Wait for `/health` to report `status: ok` and `database: reachable`.
6. In the deployed service's API docs, call `POST /v1/nav/refresh` with `X-API-Key`. Confirm it returns a nonzero record count, date range, payload hash and validation status.
7. Confirm `GET /v1/nav/status` and `GET /v1/nav/schemes?q=...` work with the same API key.
8. In GitHub repository Settings → Secrets and variables → Actions, add `MF_TERMINAL_API_URL` (base URL without trailing slash) and `MF_TERMINAL_API_KEY` (same API key). Enable Actions and run “Daily AMFI NAV refresh” manually once. Verify the workflow output and API status.

## Acceptance checks before calling this production-ready

- [ ] Live official AMFI fetch succeeds from the deployed service.
- [ ] Parsed record count is plausible and nonzero; latest NAV date is reviewed.
- [ ] Snapshot is persisted across a service restart/redeploy.
- [ ] Duplicate and invalid row counts are reviewed; no silent empty ingestion.
- [ ] API key protection is tested for all data endpoints.
- [ ] Scheduled GitHub Actions run succeeds and failure is visible.
- [ ] A later run updates retrieval timestamps without duplicate scheme/date rows.
- [ ] AMC cross-check and historical backfill are still separate acceptance items.
