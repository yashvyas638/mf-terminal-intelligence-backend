# Free-tier security and recovery controls

This runbook keeps the current Supabase project and Render deployment in place. It adds controls that work without upgrading Supabase.

## 1. Daily encrypted database backup

Workflow: `.github/workflows/supabase-free-tier-backup.yml`

- Runs daily at 23:30 UTC (05:00 IST) and on manual dispatch.
- Uses the supported Supabase CLI logical export for roles, schema and data.
- Encrypts the compressed archive with `age` before uploading it anywhere.
- Keeps a 30-day encrypted GitHub Actions artifact as a secondary recovery copy.
- Requires a verified encrypted off-site copy in Cloudflare R2 or another S3-compatible object store. A GitHub artifact alone is not accepted as a successful or durable backup.
- Never writes database exports into the repository or workflow logs.

### Activation status

The operational backup and P0 audit workflows, plus the read-only audit script, are installed on the repository's default branch (`main`). Their daily schedules and manual dispatch entry points are therefore active. The application source remains on `audit/production-foundation`; these standalone operational files were installed on `main` without merging the unrelated application history.

The first default-branch executions were triggered and stopped at configuration validation because the required Actions secrets were absent. No database export, Auth operation, or production mutation was attempted. The currently confirmed missing values were: backup — `SUPABASE_DB_URL`, `BACKUP_AGE_RECIPIENT`, `BACKUP_S3_BUCKET`, `BACKUP_S3_ENDPOINT`, `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY`; P0 audit — `SUPABASE_DB_URL`, `MF_TERMINAL_API_KEY`. The Render URL is configured directly in the workflow. Add the secrets described below; subsequent scheduled/manual runs will execute the actual checks and encrypted backup.

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

After adding the required secrets, open Actions → Supabase Free-Tier Encrypted Backup → Run workflow. A successful run must show export, checksum verification, encryption, GitHub artifact upload, R2 upload and R2 `head-object` verification, remote download and encrypted-object SHA-256 verification as green. The encrypted archive must survive the export step and be removed only by final cleanup. Until that first run succeeds, there is no completed automated backup.

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

This is a practical browser-side mitigation, not server-enforced leaked-password protection. A caller who invokes Supabase Auth directly can bypass it. Supabase's Before User Created hook does not receive the submitted password, so it cannot independently perform this exact check; a server-side password-verification hook requires a plan/feature that exposes the submitted password to the hook. Keep native Auth minimum-length and password-strength controls enabled as well.

## 3. Daily P0 production readiness audit

Workflow: `.github/workflows/p0-production-readiness.yml`

The read-only audit checks:

- Render `/health` and authenticated `/v1/nav/status`.
- Supabase Alembic revision and production connection.
- RLS and restrictive deny policies on the five backend-only tables.
- No direct anon/authenticated table privileges and retained `service_role` read access.
- RLS and client privilege posture on the additional internal tables.
- Every public table is checked against a strict allowlist: only six intended authenticated read surfaces are allowed, with owner-scoped policies for portfolio data; every other public table must deny all direct anon/authenticated privileges.
- Confirmed Auth user count and portfolio-owner count (and fails P0 when fewer than two confirmed users or two portfolio owners exist).
- Portfolio-goal ownership integrity: every goal must belong to a confirmed Auth user, and any linked portfolio must belong to that same user.

It does not mutate data, create test users, trigger NAV refreshes, or restore backups.

Add these repository Actions secrets:

| Secret | Value |
|---|---|
| `SUPABASE_DB_URL` | Same PostgreSQL connection string used by the backup workflow. |
| `MF_TERMINAL_API_KEY` | Existing operator API key stored in Render. |

The public Render URL is configured directly in the workflow; it does not need to be stored as a secret.

The audit runs daily at 22:30 UTC (04:00 IST), ahead of the 23:30 UTC (05:00 IST) backup, and can be started manually. It fails the P0 gate when fewer than two confirmed accounts or separately owned portfolios exist. Therefore, a green operational audit alone does not close the two-account acceptance gate. Close that gate only after two real confirmed accounts each create/read their own representative portfolio and cross-account reads/writes are verified to be denied.



## 4. Verified project state (2026-11-16)

The linked Supabase organization currently reports the **Free** plan. Supabase's current password-security documentation states that native leaked-password protection is available on Pro and above. Do not claim this native control can be enabled on this Free project. Keep the shared browser-side HIBP range check as a defence-in-depth mitigation, keep the strongest available minimum-length/character requirements in Auth settings, and re-evaluate native protection after an approved plan change. The browser check remains bypassable by direct Auth API callers.

A live read-only database check found one confirmed Auth account, zero rows in `public.portfolios`, zero distinct portfolio owners, and one existing `public.portfolio_goals` row. The goal is owned by the existing confirmed Auth account but is not linked to a portfolio. Preserve it; do not delete or reassign it. The audit now reports confirmed goal-owner integrity separately from portfolio-link status, and fails if a goal is linked to a portfolio owned by a different account. Two-user isolation is **not verified**: no second real confirmed account or separate owner-owned portfolio exists. A privileged SQL query is not evidence of RLS isolation. The live attempt to run as `authenticated` was denied access to `auth.users`, which is expected; never grant that access to make a test pass.

The Supabase management API confirms the organization plan is Free. The current security advisor continues to report `auth_leaked_password_protection` as WARN and 11 informational RLS-enabled/no-policy findings. Those 11 tables must remain without direct client privileges where intended; do not add permissive policies just to silence the advisor.

GitHub Actions currently exposes empty environment values for the required secrets in the failed P0 and backup jobs. This integration cannot create repository Actions secrets or retrieve the database password, and no credential should be pasted into chat. Until the owner configures the required secrets, no live audit, export, R2 upload, or restore can run. Do not create fake Auth users, synthetic portfolio owners, or claim scheduled jobs are successful based on dispatch alone.

### Current verified P0 disposition

| Gate | Current status | Why |
|---|---|---|
| Native leaked-password protection | Blocked by Free plan | Supabase documents this as Pro+; browser HIBP is mitigation only |
| Two-account isolation | Not verified | 1 confirmed user, 0 portfolios, 0 portfolio owners |
| Encrypted backup | Not run | Required GitHub Actions secrets are absent |
| Isolated restore | Not run | No verified encrypted backup exists |
| Operational monitoring | Installed, not operationally proven | Workflows are on `main` but executions stop at secret validation |

## 5. Current limits and next P0 gate

- Browser HIBP screening cannot stop direct Supabase Auth API callers. Native server-side leaked-password protection depends on Supabase plan/feature availability; verify the current project dashboard rather than assuming the browser mitigation is equivalent.
- GitHub Actions database, encryption and R2 secrets must be configured; no credentials are committed. Do not paste any of these values into chat or commit them to the repository.
- The first successful encrypted backup, verified R2 object size and remote SHA-256, successful decryption/checksum validation, and a successful isolated restore are required before the backup/restore gate can be marked complete.
- Two-account production isolation, full live AMFI ingestion evidence, endpoint smoke checks, and a review of the backup's documented exclusions remain separate P0 acceptance gates.
- P1 research implementation must not be represented as complete until P0 exit criteria are met.

### Exact P0 closure evidence

| Gate | Evidence required to close |
|---|---|
| Native password control | Supabase Auth dashboard/export confirms the strongest available native password policy; browser-side HIBP remains explicitly classified as bypassable mitigation. |
| Two-account isolation | Two real confirmed accounts; one separately owned portfolio per account; positive owner reads and negative cross-owner read/write tests through the deployed API. |
| Encrypted backup | Successful default-branch run; encrypted artifact retained; R2 object downloaded back and both size and SHA-256 verified; no plaintext dump retained in runner. |
| Restore drill | Decrypt with offline identity; SHA-256 verification; restore into a separate isolated Supabase project; schema/data counts and application smoke tests reconciled. |
| Operational schedule | Scheduled workflow execution on `main` completes its full job, not merely workflow dispatch or preflight. |
