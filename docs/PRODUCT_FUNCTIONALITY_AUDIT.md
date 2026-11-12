# Product functionality audit — 2026-11-12

## Executive finding

The repository has a useful backend foundation, but it is not yet the complete Mutual Fund Intelligence Terminal in the product blueprint. This branch adds missing authentication and portfolio workflows. Those browser changes are not production-verified until latest CI, deployment and real browser tests pass.

## Authentication

- Main dashboard and Research Terminal use Supabase email/password authentication.
- Sign-in is a form (Enter submits); email and password are validated before requests.
- Sign-up confirmation messaging, password-reset email, password update, sign-out and session restoration are implemented.
- Auth state changes hydrate the Research Terminal workspace; the dashboard clears private portfolio and transaction UI state on sign-out.
- Supabase Auth logs for recent failed attempts showed requests with missing email/phone fields. The Research Terminal's previous controls did not validate credentials; this branch now blocks blank/invalid credentials before sending the request.
- Backend validates protected bearer tokens against Supabase Auth `/auth/v1/user`.
- Render environment variables `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` were set. Live Supabase Email provider, Site URL, redirect allow-list, SMTP delivery and real browser confirmation/reset still require verification.

## Implemented API capabilities (not equivalent to complete UI)

- NAV health/status, scheme search/list, scheme details and NAV history.
- Single-scheme performance/research metrics, screener and 2–10 scheme comparison.
- Portfolio create/list, transaction create/list, statement CSV preview/import, void/audit, valuation and rebalance preview.
- User ownership checks and PostgreSQL RLS foundations.
- Latest NAV feed parser/ingestion and historical backfill planner, checkpoint and atomic persistence foundations.
- GitHub Actions daily latest-NAV refresh schedule is configured for Monday–Saturday at 17:15 UTC (22:45 IST). Required repository secrets and successful scheduled runs are not independently verified here.
- Historical NAV HTTP adapter is not enabled: AMFI's official page states a maximum 90-day download window, but the exact request parameters and response contract still need a live official-form capture and fixture validation.

## Major product gaps

| Area | Current state | Missing before product-grade |
|---|---|---|
| Authentication | Dashboard and Research Terminal flows implemented in this PR; live E2E pending | Verified provider settings, email delivery, redirect configuration and two-account browser test |
| Home | Basic metrics and data health | Portfolio-first command centre, alerts, activity and actionable insights |
| Fund Explorer | Basic text search and 30-row page | Filters, pagination, AMC/category/plan/option/benchmark metadata and watchlist |
| Fund profile | Basic NAV/ISIN/performance detail | Factsheet, AUM, expense ratio, manager, benchmark, exit load, documents and coverage view |
| Research | NAV-derived CAGR/volatility/drawdown and ratios | Full verified historical NAV, calendar returns, benchmark TRI, peer context and methodology UI |
| Compare | Scheme-code based comparison | Like-for-like plan/option/benchmark/category validation and charts |
| Portfolio | Create/list, valuation, statement preview/import, manual BUY/SELL entry, transaction history and audited void UI (this PR; end-to-end pending) | Holdings-level allocation/gain/loss, cashflow/XIRR dashboard and multi-portfolio overview |
| Rebalance | Target-weight preview | Constraints, tax/exit-load estimates, drift visualisation, scenario history and approval workflow |
| Holdings intelligence | Not implemented | Factsheet holdings ingestion, security master, overlap and concentration |
| Macro/stress | Not implemented | RBI/macro feeds, regime indicators and reproducible stress scenarios |
| Goals/tax/reports | Not implemented | Goal tracking, tax lots, capital-gains reports and exports |
| AI research | Not implemented | Source-linked assistant, citations, explainability and report builder |
| Operations | CI, migrations, daily NAV workflow and basic deployment | Verified scheduled runs, historical coverage dashboard, freshness alerts, backup/restore drill, operator controls and production E2E |

## Priority order

1. **P0-A Auth release gate:** Render environment, Supabase Email provider, Site URL, allowed redirects, SMTP/delivery, sign-up confirmation, sign-in, reset, sign-out, session refresh and two-user isolation.
2. **P0-B Product workflow gate:** authenticated first-run empty state; create portfolio; add BUY/SELL; import preview/confirm; valuation; transaction history and audited void; sign out/in and verify persistence.
3. **P0-C Data gate:** official AMFI historical request contract, historical coverage by scheme, idempotent replay, correction provenance, freshness and reconciliation.
4. **P1 Fund research:** fund master enrichment, history, rolling/calendar returns, benchmark TRI, peer comparisons and screener UI.
5. **P2–P6:** holdings overlap, macro/stress, optimisation, tax/goals/reports, AI research and production hardening.

## Evidence boundaries

- CI success proves only the commit and tests actually run in CI; it does not prove live Supabase settings, SMTP delivery or real browser sign-up.
- Setting Render environment variables triggers a deployment but does not prove that the expected commit is live.
- No test account was created and no production portfolio/NAV records were modified for this audit.
- Latest branch UI changes require the current CI run and live browser verification before merge/deploy.
