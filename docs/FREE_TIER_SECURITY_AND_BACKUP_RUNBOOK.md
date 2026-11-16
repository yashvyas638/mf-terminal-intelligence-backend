# Free-tier security and recovery controls

This runbook keeps the current Supabase project and Render deployment in place. It adds controls that work without upgrading Supabase.

## 1. Daily encrypted database backup

Workflow: `.github/workflows/supabase-free-tier-backup.yml`

- Runs daily at 23:30 UTC (05:00 IST) and on manual dispatch.
- Uses the supported Supabase CLI logical export for roles, schema and data.
- Encrypts the compressed archive with `age` before uploading it anywhere.
- Keeps a 30-day encrypted GitHub Actions artifact as a recovery copy.
- Requires a verified encrypted off-site copy in Cloudflare R2 or another S3-compatible object store; a GitHub artifact alone is not accepted as a durable backup.
- Never writes database exports into the repository or workflow logs.

### Activation status

The operational backup and P0 audit workflows, plus the read-only audit script, are installed on the repository's default branch (`main`). Their daily schedules and manual dispatch entry points are therefore active. The application source remains on `audit/production-foundation`; these standalone operational files were installed on `main` without merging the unrelated application history.

The first default-branch executions were triggered and correctly stopped at configuration validation. GitHub Actions confirmed these missing values: backup — `SUPABASE_DB_URL`, `BACKUP_AGE_RECIPIENT`, `BACKUP_S3_BUCKET`, `BACKUP_S3_ENDPOINT`, `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY`; P0 audit — `SUPABASE_DB_URL`, `MF_TERMINAL_API_KEY`. The Render URL is configured directly in the workflow. No database export or mutation was attempted. Add the secrets described below; subsequent scheduled/manual runs will execute the actual checks and encrypted backup.

### One-time GitHub configuration

Create a private backup bucket in Cloudflare R2 (or another S3-compatible provider). Generate an age key pair on a trusted local machine:

```bash
age-keygen -o mf-terminal-backup-identity.txt
```

Keep `mf-terminal-backup-identity.txt` offline in a password manager or encrypted offline storage. Do not upload it to GitHub, Render, Supabase or this repository. Copy only the public `age1...` recipient printed by `age-keygen`.

Add these repository Actions secrets under GitHub → Settings → Secrets and variables → Actions:

| Secret | Required | Value |
|---|---:|---|
| `SUPABASE_DB_URL` | Yes | Supabase PostgreSQL connection string. Prefer the Session Pooler URL if the runner cannot connect directly. |
| `BACKUP_AGE_RECIPIENT` | Yes | Public `age1...` recipient; never the private identity. |
| `BACKUP_S3_BUCKET` | Yes | Existing private R2/S3 bucket name. |
| `BACKUP_S3_ENDPOINT` | Yes | R2 endpoint, e.g. `https://<account-id>.r2.cloudflarestorage.com`. |
| `BACKUP_S3_ACCESS_KEY_ID` | Yes | R2/S3 access key scoped to this bucket/prefix with `ListBucket`, `GetObject` and `PutObject` permissions only. |
| `BACKUP_S3_SECRET_ACCESS_KEY` | Yes | Matching R2/S3 secret. The workflow preflights bucket access and the age recipient before exporting production data. |

All six backup secrets are required. The workflow fails before connecting to production unless both the database/encryption configuration and the durable R2/S3 destination are present. Daily encrypted copies use the `mf-terminal-intelligence/daily/` prefix; the first run of each month also writes a monthly copy under `mf-terminal-intelligence/monthly/`. Configure R2 lifecycle rules to expire daily objects after 45 days and monthly objects after 400 days. Keep the bucket private and scope the access key to this bucket only.

After adding the required secrets, open Actions → Supabase Free-Tier Encrypted Backup → Run workflow. A successful run must show export, checksum verification, encryption, GitHub artifact upload, R2 upload and R2 `head-object` verification as green. Until that first run succeeds, there is no completed automated backup.

### Restore procedure

1. Download the encrypted `.tar.gz.age` artifact from a successful workflow run (or retrieve it from R2).
2. On a trusted machine with `age` installed, decrypt it using the private identity kept offline:

   ```bash
   age --decrypt --identity mf-terminal-backup-identity.txt --output backup.tar.gz backup.tar.gz.age
   tar -xzf backup.tar.gz
   sha256sum --check SHA256SUMS
   ```

3. Restore first to a separate, isolated PostgreSQL/Supabase project. Review Supabase-managed roles, extensions, default privileges and migration state before applying the exports. Use a privileged database connection and stop on the first SQL error.
   Before restoring the schema, follow Supabase's privilege guidance on the target: `ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;`. Inspect the dump's GRANT/REVOKE statements and confirm the intended RLS posture before applying it; never assume a new target's defaults are safe.

   After verifying that the target is a fresh isolated Supabase project and its managed roles/extensions are present, restore in this order (use the target's privileged Session Pooler URI; do not put it in the repository):

   ```bash
   export RESTORE_DB_URL='postgresql://...'
   psql "$RESTORE_DB_URL" -v ON_ERROR_STOP=1 -f roles.sql
   psql "$RESTORE_DB_URL" -v ON_ERROR_STOP=1 -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;"
   psql "$RESTORE_DB_URL" -v ON_ERROR_STOP=1 -f schema.sql
   psql "$RESTORE_DB_URL" -v ON_ERROR_STOP=1 -f data.sql
   ```

   Review the target's existing managed roles and the SQL dump before executing. If a role already exists or a statement conflicts with Supabase-managed objects, stop and reconcile the target; do not use `--no-owner`/blanket grants as a shortcut.
4. Run the application migration checks, API smoke tests, private-table grant/RLS checks and data reconciliation against that isolated target.
5. Only plan a production recovery after the isolated restore is verified and a maintenance window/rollback path is approved. Never use production as the restore test target.

### Network safety

The workflow intentionally does not set `SUPABASE_YES` and never auto-approves removal of a Supabase network ban. If the CLI reports that a network ban or network restriction blocks the connection, the job stops. Resolve connectivity through an approved Session Pooler/database allowlist route; do not remove an existing production network restriction merely to make backups pass. The export commands are read-only.

### Important backup scope

Supabase CLI logical dumps exclude Supabase-managed `auth`, `storage` and extension schemas. Storage object bytes are not included either. The dump therefore protects the application's PostgreSQL schema, application data and custom role definitions, but is not a complete Supabase account/Storage backup.

Auth accounts cannot be recreated with their original passwords from this export. Preserve account lifecycle through verified email invitations/password resets. Storage objects need their own object-store backup if the application starts storing user files. Do not treat this logical backup as a replacement for Supabase's managed physical backups or PITR.

GitHub artifact retention is only 30 days and is a secondary recovery copy. R2/S3 is mandatory for durable off-site retention; apply the daily/monthly lifecycle policies and periodically perform a restore drill.

## 2. Leaked-password screening on Free tier

Both the main dashboard and Research Terminal now use the same shared, tested password-screening module before new account creation and password-reset changes against Have I Been Pwned's free Pwned Passwords range API.

- The browser computes the SHA-1 hash locally.
- Only the first five hash characters are sent to HIBP; the password and full hash are never sent.
- The response is checked locally, with the API's `Add-Padding: true` option and no-store caching.
- The response parser validates every returned suffix/count row and rejects malformed, empty, oversized or non-success responses. Network failures and timeouts fail closed.
- Known compromised passwords are rejected before Supabase Auth is called.
- If the HIBP request fails or times out, signup/password change fails closed and asks the user to retry.

This is a practical Free-tier mitigation, not identical to Supabase's native server-side leaked-password protection. A user who bypasses either browser UI and calls Supabase Auth directly can bypass the browser check. Supabase's Before User Created hook is available on Free, but its event does not contain the submitted password; the password-verification hook is not available on Free. Keep the native Auth minimum length/complexity controls enabled as well.

## 3. Daily P0 production readiness audit

Workflow: `.github/workflows/p0-production-readiness.yml`

The read-only audit checks:

- Render `/health` (including the validated `build_commit` fingerprint) and authenticated `/v1/nav/status`.
- Supabase Alembic revision and production connection.
- RLS and restrictive deny policies on the five backend-only tables.
- No direct anon/authenticated table privileges and retained `service_role` read access.
- RLS and client privilege posture on the additional internal tables.
- Every public table is checked against a strict allowlist: only six intended authenticated read surfaces are allowed, with owner-scoped policies for portfolio data; every other public table must deny all direct anon/authenticated privileges.
- Confirmed Auth user count and portfolio-owner count (reported as evidence, not fabricated).

It does not mutate data, create test users, trigger NAV refreshes, or restore backups.

Add these repository Actions secrets:

| Secret | Value |
|---|---|
| `SUPABASE_DB_URL` | Same PostgreSQL connection string used by the backup workflow. |
| `MF_TERMINAL_API_KEY` | Existing operator API key stored in Render. |

The public Render URL is configured directly in the workflow; it does not need to be stored as a secret.

The audit runs daily at 22:30 UTC (04:00 IST), ahead of the 23:30 UTC (05:00 IST) backup, and can be started manually. It intentionally reports a warning—not a false pass—when fewer than two confirmed accounts or portfolio owners exist. Real two-account isolation still requires two real accounts and representative data owned by each account.

## 4. Verified project state (2026-11-16)

The linked Supabase organization reports the **Free** plan. Native leaked-password protection is documented as Pro+; do not claim the browser-side HIBP range check is equivalent. Keep the browser check as defence-in-depth, retain the strongest available Auth minimum-length/complexity controls, and record the native-control limitation until an approved plan change.

The latest live read-only database audit found one confirmed Auth account, zero rows in `public.portfolios`, zero distinct portfolio owners, and one existing `public.portfolio_goals` row. The goal belongs to the existing confirmed Auth account but is not linked to a portfolio. Preserve it; do not delete or reassign it. No second real confirmed account or separately owned portfolio exists, so production two-account isolation is **not verified**. Code-level simulated two-user tests and PostgreSQL RLS tests are useful evidence, but they are not a substitute for two real Auth accounts and deployed API tests.

The security advisor reports `auth_leaked_password_protection` as WARN and 11 informational RLS-enabled/no-policy findings. Those deny-all internal tables must remain inaccessible to direct clients; do not add permissive policies to silence informational findings. Effective default privileges also expose a future-object risk: `postgres`, `pg_database_owner` and `supabase_admin` have built-in `PUBLIC EXECUTE` defaults, and `supabase_admin` has explicit `anon`/`authenticated` defaults for public tables, sequences and functions. Candidate migration `0029_admin_default_acl` closes these defaults; production remains at `0028_restrictive_private_access` until an authorised migration run.

The latest daily-feed snapshot was retrieved at `2026-11-12 02:53 UTC` with maximum NAV date `2026-11-11`. The 1M/1Y/3Y/5Y research snapshots each contain 8,713 schemes but are also as-of 2026-11-11. The hybrid historical backfill has 168 completed daily and 144 completed month-end checkpoints; 780 paused daily checkpoints are deliberately superseded by `StorageOptimizedHybridPlan`, not failed requests. The live AMFI performance/taxonomy audit checked 43 categories, 86 requests and 2,140 rows (2,073 current allowlisted identifiers; 67 legacy/rejected diagnostic-only rows) with zero database writes.

The P0 audit and encrypted-backup workflows exist on default `main`, but the latest Actions secret preflight blocks execution. The default-branch backup workflow's cross-step `$STAMP` defect was fixed in commit `8a32616511c88a109e41ae4c782bb25e2b2bb82b`; the R2 step now imports the timestamp from the backup step output and verifies daily/monthly remote size and SHA-256. The push-triggered run stopped at configuration preflight because required secrets are absent; no database export or production connection was attempted. The candidate validator now guards against this regression. The NAV refresh and AMFI live-source-monitor workflows are only on the candidate branch, not default `main`; therefore no active production NAV scheduler is evidenced. The candidate and default-branch Render blueprints disagree on service name, plan and startup command; the actual Render service, deployed branch, plan and DB role remain unverified.

### Current verified P0 disposition

| Gate | Current status | Why |
|---|---|---|
| Native leaked-password protection | Blocked by Free plan | Browser HIBP screening is mitigation only |
| Auth provider and browser E2E | Not verified | Confirm-email/SMTP/redirect settings and real signup/reset flows remain untested |
| Two-account isolation | Not verified | 1 confirmed user, 0 portfolios, 0 portfolio owners |
| Default ACL lockdown | Candidate code and CI pass; production not migrated | Migration 0029 requires a separate authorised migration connection |
| Encrypted backup | Not run | Required GitHub Actions secrets are absent; default-branch R2 verification bug must be integrated |
| Isolated restore | Not run | No verified encrypted backup exists |
| NAV freshness/scheduler | Blocked | Latest stored NAV date 2026-11-11; refresh workflow is candidate-only |
| Render deployment mapping | Not verified | Blueprint identity/plan/startup mismatch; actual service not inspected |
| Branch integration | Blocked | PR #1 is 604 commits ahead, 53 behind, 145 changed files and currently not mergeable |

## 5. Current limits and next P0 gate

- Browser HIBP screening cannot stop direct Supabase Auth API callers. Native leaked-password protection depends on Supabase plan/feature availability; verify the project dashboard rather than assuming the browser mitigation is equivalent.
- GitHub Actions database, encryption and R2 secrets must be configured privately; no credentials are committed or pasted into chat.
- The first successful encrypted backup, verified R2 object size and remote SHA-256, successful decryption/checksum validation, and a successful isolated restore are required before the backup/restore gate can be marked complete.
- The candidate Render blueprint requires separate runtime `DATABASE_URL` and privileged direct-session `MIGRATION_DATABASE_URL`. The runtime role must be a trusted non-superuser; the application now rejects PostgreSQL superuser runtime credentials. The migration URL is used only for Alembic and is unset before Uvicorn starts. Do not sync the blueprint until the live service identity, plan, branch and DB roles are confirmed.
- The NAV refresh and AMFI monitor must be activated on default `main` or through an explicitly approved Render Cron service. Then observe a successful scheduled run and confirm retrieval freshness under 36 hours plus effective NAV age within the configured maximum.
- Two-account production isolation, live Auth browser E2E, full AMFI ingestion evidence, endpoint smoke checks and a review of backup exclusions remain separate P0 acceptance gates.
- P1 research implementation must not be represented as complete until P0 exit criteria are met.

### Exact P0 closure evidence

| Gate | Evidence required to close |
|---|---|
| Native password control | Supabase Auth dashboard confirms the strongest available native policy; native leaked-password protection is enabled after an approved plan change or the limitation is formally accepted. |
| Auth and email confirmation | Confirm-email, Site URL, redirect allow-list and SMTP are verified; real signup, confirmation, login, session expiry, password reset and sign-out pass in a browser. |
| Two-account isolation | Two real confirmed accounts; one separately owned portfolio per account; positive owner reads and negative cross-owner read/write tests through the deployed API. |
| Default ACL lockdown | Apply migration 0029 through an authorised direct-session migration URL; effective defaults show no PUBLIC/anon/authenticated grants on future public tables, sequences or functions; managed-schema explicit grants remain intact. |
| Encrypted backup | Successful default-branch run; encrypted artifact retained; R2 object downloaded back and both size and SHA-256 verified; no plaintext dump retained on runner. |
| Restore drill | Decrypt with offline identity; SHA-256 verification; restore into a separate isolated Supabase project; schema/data counts and application smoke tests reconciled. |
| NAV schedule and freshness | Refresh workflow active on default branch or approved Render Cron; observe a successful scheduled run; verify current NAV date, retrieval freshness and reproducible 1M/1Y/3Y/5Y snapshots. |
| Render release | Confirm existing service identity, plan, deployed branch/SHA, trusted non-superuser runtime role, privileged migration role, required environment and start command; no accidental service creation, rename or plan change. |
| Branch integration | Reconcile the 51 commits on main, review the full 144-file PR diff, resolve add/add conflicts in the P0 audit/backup workflow, runbook and audit script, then verify a mergeable PR. |
| Operational audit | A successful default-branch P0 audit completes all checks with two real confirmed users and separate portfolio owners; no configuration-only pass is accepted. |
