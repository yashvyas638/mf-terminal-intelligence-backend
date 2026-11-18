# Start here

## Current source of truth

The active application code is on [audit/production-foundation](https://github.com/yashvyas638/mf-terminal-intelligence-backend/tree/audit/production-foundation). The default main branch currently carries the operational GitHub workflows and repository entry-point documentation; it is not yet the merged application release.

Before running the application, check out the active branch:

~~~bash
git clone https://github.com/yashvyas638/mf-terminal-intelligence-backend.git
cd mf-terminal-intelligence-backend
git checkout audit/production-foundation
~~~

Read README.md first, then:

## Local setup

Use Python 3.12.16.

~~~bash
python -m venv .venv
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
~~~

For local development only:

~~~bash
set ENVIRONMENT=development
set DATABASE_URL=sqlite:///./mf_terminal.db
set API_KEY=replace-with-a-long-random-secret
alembic upgrade head
uvicorn app.main:app --reload --port 8000
~~~

On macOS/Linux, use export instead of set.

Open http://127.0.0.1:8000/health.

## Before submitting a change

~~~bash
ruff check .
pytest -q
~~~

The CI pipeline also runs SQLite and PostgreSQL migration/test suites plus live, read-only AMFI source-contract checks.

## Production safety

- Render is configured to deploy from audit/production-foundation; verify the actual service configuration before changing it.
- Keep runtime DATABASE_URL, migration-only MIGRATION_DATABASE_URL, and API_KEY in Render's secret settings. Never commit or paste secrets into chat.
- Do not reuse the runtime database URL as the privileged migration URL.
- Do not run production migrations until a supported migration identity and a verified backup/restore path are available.
- The current production Alembic revision is documented in the delivery checklist; check the live database before assuming migrations have run.
- The encrypted backup workflow requires its GitHub Actions secrets and a successful off-site restore verification. A green code CI run is not proof that a production backup exists.

## Project documents

- Product delivery checklist: docs/PRODUCT_DELIVERY_CHECKLIST.md
- Engineering playbook: docs/ENGINEERING_PLAYBOOK.md
- Final release runbook: docs/FINAL_RELEASE_RUNBOOK.md
- Free-tier security and backup runbook: docs/FREE_TIER_SECURITY_AND_BACKUP_RUNBOOK.md
