# Free-tier security, deployment and backup runbook

Last verified: 18 November 2026.

## Current state (do not infer completion from workflow notifications)

- Supabase project is `ACTIVE_HEALTHY`.
- The active application and Render deployment branch is `audit/production-foundation`.
- Render's actual service start command is still `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`; it does not yet match the reviewed blueprint/Procfile command.
- Latest Render deployment attempt failed at startup because `MIGRATION_DATABASE_URL` was not configured. The previous successful deployment remains live.
- Production Alembic revision is `0028_restrictive_private_access`; repository migration head is `0030_remove_duplicate_nav_index`.
- Migration 0029 fails closed when the connected role cannot alter default privileges for every role with CREATE on `public`. The inspected Supabase `postgres` identity cannot manage `supabase_admin` defaults. Do not weaken this check or grant unsupported role membership.
- The encrypted backup workflow has a supported Supabase CLI `--db-url` connection flag, but no backup has run: all six required GitHub Actions secrets are absent.
- No encrypted off-site backup or isolated restore has been verified.
- CI on cleanup PR #145 passes SQLite, PostgreSQL and live read-only AMFI checks; this is not a production deployment or restore test.

## Render configuration

Render dashboard: https://dashboard.render.com/web/srv-dbq5gfbrjlhs73bah0l0

Required private variables:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Runtime PostgreSQL connection using a dedicated non-superuser application role |
| `MIGRATION_DATABASE_URL` | Separate direct-session migration connection, authorised for the full Alembic chain |
| `API_KEY` | Server-side operator key, minimum 32 characters |
| `ENVIRONMENT` | `production` |

Do not use the same URL for runtime and migrations. Do not paste credentials into GitHub source, issues, logs, or ChatGPT.

Reviewed startup command:

~~~bash
alembic upgrade head && unset MIGRATION_DATABASE_URL && uvicorn app.main:app --host 0.0.0.0 --port $PORT
~~~

Before syncing the blueprint, confirm the migration identity is approved and can pass migration 0029. Merely adding a PostgreSQL URL is not sufficient. After configuration, verify the service command in the Render dashboard, deploy, check `/health`, and confirm the health response reports the intended full commit SHA.

## GitHub encrypted backup secrets

Configure these under repository Settings -> Secrets and variables -> Actions -> New repository secret. Never share the values in chat.

| Secret | Required value |
|---|---|
| `SUPABASE_DB_URL` | Direct PostgreSQL connection URI for the correct Supabase project; keep credentials private |
| `BACKUP_AGE_RECIPIENT` | `age1...` public encryption recipient; never the private identity |
| `BACKUP_S3_BUCKET` | Private S3-compatible/R2 bucket name |
| `BACKUP_S3_ENDPOINT` | HTTPS endpoint for the bucket |
| `BACKUP_S3_ACCESS_KEY_ID` | Restricted backup-writer access key |
| `BACKUP_S3_SECRET_ACCESS_KEY` | Matching secret access key |

The workflow exports roles, schema and data SQL, checksums the source files, packages and encrypts the archive with age, uploads a short-retention GitHub recovery copy, then uploads and downloads the off-site copy to verify byte size and SHA-256. Supabase-managed auth/storage/extension schemas and storage object bytes are excluded; this is not a full physical backup.

Run the workflow manually only after configuring all six secrets. A successful workflow must be followed by a separate restore drill using the private age identity into an isolated Supabase project. Verify schema, row counts and application smoke tests. Do not restore over production as a test.

## Auth and data access

- Browser requests use Supabase access tokens; portfolio reads/writes must be scoped to the verified user ID.
- `X-API-Key` is for trusted server-side automation only; never embed it in browser assets.
- `anon` currently has no direct table grants. `authenticated` has SELECT only on the six approved read surfaces identified in the repository audit.
- Supabase advisor reports 11 RLS-enabled backend tables without policies. Keep these backend-only and do not add permissive policies to silence advisor warnings.
- Native leaked-password protection is disabled on the current Free plan. Browser-side password screening is only a bypassable mitigation, not equivalent to native Auth enforcement.

## Release gates

1. Obtain an approved Supabase migration identity that can satisfy migration 0029; do not bypass the preflight.
2. Establish and verify a backup plus isolated restore before production DDL.
3. Configure Render secrets privately and sync the reviewed start command; verify the live commit fingerprint and health.
4. Apply Alembic revisions 0029 and 0030 only after backup and migration-identity approval.
5. Run two-account ownership/isolation tests and a real portfolio/TWT report using verified holdings data in a non-production environment.
6. Review Supabase security/performance advisors and confirm no unexpected grants, policies or schema drift.

See `docs/REPOSITORY_AUDIT_2026-11-18.md` and `docs/PRODUCT_DELIVERY_CHECKLIST.md` for the current evidence and detailed outstanding items.
