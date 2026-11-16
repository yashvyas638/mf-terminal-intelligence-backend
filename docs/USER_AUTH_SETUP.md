# User Authentication and First-Run Setup

## User experience

- Open the Render app URL.
- Create an account with an email address and password, or sign in.
- If email confirmation is enabled, confirm the email and return to the same app URL.
- Each signed-in account sees only portfolios it owns.
- Sign out before switching accounts on a shared device.
- No backend API key is entered, copied, or stored in the browser.

## Render environment

Set these service environment variables on the existing Render web service:

| Variable | Value |
| --- | --- |
| `SUPABASE_URL` | `https://zgfdvhzhvccsfmpoaqah.supabase.co` |
| `SUPABASE_PUBLISHABLE_KEY` | The project's active `sb_publishable_...` key |

The publishable key is designed for browser use. Never put a Supabase secret/service-role key in static files, GitHub, or user instructions.

Keep `API_KEY` server-side in Render. It remains an operator credential for the NAV refresh endpoint and trusted automation; it is not part of the normal dashboard or research sign-in flow.

## Supabase Auth settings

In Supabase Dashboard → Authentication → Providers:
1. Enable the Email provider and email/password sign-up.
2. Decide whether email confirmation is required. Keeping confirmation enabled is recommended.
3. Set the Site URL to `https://mf-terminal-intelligence-backend.onrender.com`.
4. Add `https://mf-terminal-intelligence-backend.onrender.com` to the allowed redirect URLs.
5. If using a custom SMTP provider, verify sender/domain and delivery before inviting family users.

The browser uses the current origin as the email confirmation redirect.

## Database migration 0010

Migration `0010_user_auth_rls`:
- Adds `owner_user_id` to portfolios.
- Refuses to proceed if any portfolio has no verified owner; it never guesses.
- Enables RLS on the nine public application tables.
- Grants authenticated users read-only access to reference NAV data and owner-filtered portfolio rows.
- Does not grant browser users direct insert/update/delete privileges. Writes continue through validated FastAPI routes.
- Leaves server-side ingestion and the trusted PostgreSQL service role on the backend.

Before production deployment:
- Confirm the live portfolio and transaction counts.
- Take and verify a restorable database backup.
- Review the migration and RLS policies.
- Confirm the Render database role is trusted and not `anon` or `authenticated`.
- Deploy the approved commit and verify two separate accounts cannot see one another's portfolios.

## Verification

The CI suite runs SQLite and PostgreSQL tests, checks JavaScript syntax, applies the Alembic chain, checks least-privilege grants, and exercises portfolio row isolation under PostgreSQL RLS.

## Operational note

Supabase Auth session tokens are refreshed by the Supabase browser client. FastAPI validates each bearer token against Supabase Auth before handling protected API requests. If Auth is unavailable, protected requests fail closed with a retryable service error.
