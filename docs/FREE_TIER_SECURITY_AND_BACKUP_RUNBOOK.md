# Free-tier security and recovery controls

This runbook keeps the current Supabase project and Render deployment in place. It adds controls that work without upgrading Supabase.

## 1. Daily encrypted database backup

Workflow: `.github/workflows/supabase-free-tier-backup.yml`

- Runs daily at 23:30 UTC (05:00 IST) and on manual dispatch.
- Uses the supported Supabase CLI logical export for roles, schema and data.
- Encrypts the compressed archive with `age` before uploading it anywhere.
- Keeps a 30-day encrypted GitHub Actions artifact as a recovery copy.
- Can additionally copy the encrypted archive to Cloudflare R2 or another S3-compatible object store.
- Never writes database exports into the repository or workflow logs.

### Activation status

The operational backup and P0 audit workflows, plus the read-only audit script, are installed on the repository's default branch (`main`). Their daily schedules and manual dispatch entry points are therefore active. The application source remains on `audit/production-foundation`; these standalone operational files were installed on `main` without merging the unrelated application history.

The first default-branch executions were triggered and correctly stopped at configuration validation because `SUPABASE_DB_URL`, `BACKUP_AGE_RECIPIENT`, `MF_TERMINAL_API_URL`, and `MF_TERMINAL_API_KEY` are not currently configured as GitHub Actions secrets. No database export or mutation was attempted. Add the secrets described below; subsequent scheduled/manual runs will execute the actual checks and encrypted backup.

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
| `BACKUP_S3_BUCKET` | No | Existing R2/S3 bucket name. |
| `BACKUP_S3_ENDPOINT` | No | R2 endpoint, e.g. `https://<account-id>.r2.cloudflarestorage.com`. |
| `BACKUP_S3_ACCESS_KEY_ID` | No | R2/S3 access key with write access only to the backup bucket. |
| `BACKUP_S3_SECRET_ACCESS_KEY` | No | Matching R2/S3 secret. |

The first two secrets are enough to run the encrypted GitHub artifact backup. Configure all four S3 values to enable the second off-site copy. Use a bucket lifecycle rule (for example, retain 30 daily backups and 12 monthly backups) and enable object versioning if the provider supports it.

After adding the required secrets, open Actions → Supabase Free-Tier Encrypted Backup → Run workflow. A successful run must show both the export/encryption and artifact-upload steps as green. If R2 is configured, the R2 upload must also be green. Until that first run succeeds, there is no completed automated backup.

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
4. Run the application migration checks, API smoke tests, private-table grant/RLS checks and data reconciliation against that isolated target.
5. Only plan a production recovery after the isolated restore is verified and a maintenance window/rollback path is approved. Never use production as the restore test target.

### Important backup scope

Supabase CLI logical dumps exclude Supabase-managed `auth`, `storage` and extension schemas. Storage object bytes are not included either. The dump therefore protects the application's PostgreSQL schema, application data and custom role definitions, but is not a complete Supabase account/Storage backup.

Auth accounts cannot be recreated with their original passwords from this export. Preserve account lifecycle through verified email invitations/password resets. Storage objects need their own object-store backup if the application starts storing user files. Do not treat this logical backup as a replacement for Supabase's managed physical backups or PITR.

GitHub artifact retention is only 30 days. The optional R2/S3 copy is the durable off-site layer; apply a lifecycle policy and periodically perform a restore drill.

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

- Render `/health` and authenticated `/v1/nav/status`.
- Supabase Alembic revision and production connection.
- RLS and restrictive deny policies on the five backend-only tables.
- No direct anon/authenticated table privileges and retained `service_role` read access.
- RLS and client privilege posture on the additional internal tables.
- Confirmed Auth user count and portfolio-owner count (reported as evidence, not fabricated).

It does not mutate data, create test users, trigger NAV refreshes, or restore backups.

Add these repository Actions secrets:

| Secret | Value |
|---|---|
| `SUPABASE_DB_URL` | Same PostgreSQL connection string used by the backup workflow. |
| `MF_TERMINAL_API_URL` | `https://mf-terminal-intelligence-backend.onrender.com` |
| `MF_TERMINAL_API_KEY` | Existing operator API key stored in Render. |

The audit runs daily at 23:00 UTC (05:00 IST) and can be started manually. It intentionally reports a warning—not a false pass—when fewer than two confirmed accounts or portfolio owners exist. Real two-account isolation still requires two real accounts and representative data owned by each account.

## 4. Current limits and next P0 gate

- The native Supabase Pro-only leaked-password feature and managed daily backups remain unavailable on Free. The controls above are independent workarounds.
- GitHub/R2 secrets must be configured by a repository owner; no credentials are committed.
- The first successful encrypted backup and a successful isolated restore are required before the backup/restore gate can be marked complete.
- Two-account production isolation, full live AMFI ingestion evidence and endpoint smoke checks remain separate P0 acceptance gates.
- P1 research implementation must not be represented as complete until P0 exit criteria are met.
