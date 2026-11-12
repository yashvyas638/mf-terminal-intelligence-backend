# Product functionality audit — 2026-11-12

## Executive finding

The repository currently contains a useful backend foundation and a small dashboard. It is not yet the full Mutual Fund Intelligence Terminal described in the product blueprint. Authentication controls exist in the browser, but end-to-end onboarding depends on Supabase Auth provider, email confirmation, redirect allow-list and email delivery settings. Those dashboard settings are not verified by the connected project tools.

## Authentication: observed state

- Browser calls Supabase JS signUp, signInWithPassword, signOut and session restore.
- Backend validates protected API bearer tokens against Supabase Auth /auth/v1/user.
- Render requires SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY; both were set using the same project URL and public publishable key already referenced by the browser app.
- The UI had no form submit handler, so Enter-key sign-in was not wired.
- Auth state listener updated button visibility but did not reliably trigger workspace hydration after auth events.
- No password-reset entry point existed.
- Email confirmation relies on the Render app origin being configured as the Supabase Site URL / allowed redirect URL and on working email delivery.

## Implemented API capabilities (not equivalent to complete UI)

- NAV health/status, scheme search/list, scheme details and NAV history.
- Single-scheme performance/research metrics, screener and 2–10 scheme comparison.
- Portfolio create/list, transaction create/list, statement CSV preview/import, void/audit, valuation and rebalance preview.
- User ownership checks and PostgreSQL RLS foundations.
- Latest NAV feed parser/ingestion and durable historical backfill planning/checkpoint/persistence foundations.

## Major product gaps

| Area | Current state | Missing before product-grade |
|---|---|---|
| Authentication | Basic email/password controls | Verified provider settings, confirmation/reset flow, robust states, real two-account E2E |
| Home | Basic metrics and data health | Portfolio-first command centre, alerts, activity and actionable insights |
| Fund Explorer | Basic text search and 30-row page | Filters, pagination, AMC/category/plan/option/benchmark metadata, watchlist |
| Fund profile | Basic NAV/ISIN/performance detail | Factsheet, AUM, expense ratio, manager, benchmark, exit load, documents and history coverage |
| Research | NAV-derived CAGR/volatility/drawdown and ratios | Verified full historical NAV, rolling/calendar returns, benchmark TRI, peer context and methodology UI |
| Compare | Scheme-code based comparison | Like-for-like plan/option/benchmark/category validation and charts |
| Portfolio | Create/list, valuation, statement import | Holdings table, cashflows, XIRR, allocation, gain/loss, transaction UI and multi-portfolio dashboard |
| Rebalance | Target weight preview | Constraints, tax/exit-load estimates, drift visualisation, scenario history and approval workflow |
| Holdings intelligence | Not implemented | Factsheet holdings ingestion, security master, overlap and concentration |
| Macro/stress | Not implemented | RBI/macro feeds, regime indicators and reproducible stress scenarios |
| Goals/tax/reports | Not implemented | Goal tracking, tax lots, capital-gains reports and exports |
| AI research | Not implemented | Source-linked assistant, citations, explainability and report builder |
| Operations | CI, migrations, basic deployment | Source freshness alerts, coverage dashboard, backup/restore drill, operator controls and production E2E |

## Priority order

1. P0-A Auth release gate: Render env, Supabase Email provider, Site URL, allowed redirect, SMTP/delivery, sign-up confirmation, sign-in, reset, sign-out, session refresh and two-user isolation.
2. P0-B Product workflow gate: authenticated first-run empty state; create portfolio; add holding/transaction; import preview/confirm; valuation; transaction history; sign out/in and verify persistence.
3. P0-C Data gate: official AMFI historical request contract, historical coverage by scheme, idempotent replay, correction provenance, freshness and reconciliation.
4. P1 Fund research: fund master enrichment, history, rolling returns, benchmark TRI, peer comparisons and screener UI.
5. P2–P6: holdings overlap, macro/stress, optimisation, tax/goals/reports, AI research and production hardening.

## Evidence boundaries

- CI success proves tests in CI only; it does not prove live Supabase Auth settings, SMTP delivery or real browser sign-up.
- Setting Render environment variables triggers a deployment but does not prove the resulting deployment is live.
- No test account was created and no production portfolio/NAV records were modified for this audit.
