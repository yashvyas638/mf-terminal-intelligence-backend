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

- NAV health/status, scheme search/list with AMC/category/asset-class/plan/option filters and server-side pagination, scheme details with NAV history series and NAV history API.
- Single-scheme performance/research metrics, screener and 2–10 scheme comparison.
- Portfolio create/list, transaction create/list, statement CSV preview/import, void/audit, valuation and rebalance preview.
- User ownership checks and PostgreSQL RLS foundations.
- Latest NAV feed parser/ingestion and historical backfill planner, checkpoint and atomic persistence foundations.
- GitHub Actions daily latest-NAV refresh schedule is configured for Monday–Saturday at 17:15 UTC (22:45 IST). Required repository secrets and successful scheduled runs are not independently verified here.
- Historical NAV HTTP adapter is not enabled: AMFI's official page states a maximum 90-day download window, but the exact request parameters and response contract still need a live official-form capture and fixture validation.

## Fund Explorer classification contract

- The AMFI `NAVAll.txt` file is a grouped feed, not a flat table. The parser now carries AMC and scheme-section headers forward to each scheme row.
- The current SEBI framework (Circular HO/24/13/15(2)2026-IMD-RAC4/I/5764/2026, 26-Feb-2026) defines five broad groups: Equity Scheme, Debt Scheme, Hybrid Scheme, Life Cycle Funds and Other Schemes. See https://www.sebi.gov.in/sebi_data/attachdocs/feb-2026/1772079826878.pdf.
- Asset class is derived only where the SEBI broad group has a single meaningful asset class. Life Cycle Funds remains a distinct scheme group and is not fabricated into an asset class.
- Standard SEBI sub-categories are allow-listed per broad group. AMFI-provided detail labels (including Life Cycle maturity bands and ETF types) are retained only when explicitly present in the AMFI section header; they do not become additional SEBI broad groups.
- AMFI's explicit `Group - Sub-category` header is required; unknown suffixes such as `PowerUp` are discarded even when paired with a valid Equity Scheme group.
- Legacy AMFI group aliases are normalized only where their mapping is unambiguous. Retired Solution Oriented labels are not guessed into a current category.
- Fund Explorer and Research Terminal expose separate Scheme Group and Sub-category filters. The `Power Select` tab label is `Fund Screener`; it is a screen name, not a mutual-fund category.
- API responses and facets apply the same allow-list to new feed rows and stale persisted values, so arbitrary marketing labels cannot leak into fund cards, filters, watchlists or research metadata.
- The parser and API regression tests cover five current groups, official passive/other categories, legacy group aliases, and rejection of a deliberately invalid `PowerUp` sub-category under a valid Equity Scheme group.

## Major product gaps

| Area | Current state | Missing before product-grade |
|---|---|---|
| Authentication | Dashboard and Research Terminal flows implemented in this PR; live E2E pending | Verified provider settings, email delivery, redirect configuration and two-account browser test |
| Home | Portfolio-first command centre with consolidated value/cost/unrealized P&L, per-portfolio XIRR and NAV freshness (this PR; end-to-end pending) | Activity feed, alerts, goal progress and proactive actionable insights |
| Fund Explorer | Search, canonical scheme-group/sub-category/asset-class/AMC/plan/option filters, AMFI-header metadata extraction and server-side pagination | Watchlist, benchmark metadata and live-verified category coverage |
| Fund profile | Scheme metadata, NAV-derived metrics, coverage and historical NAV line chart (this PR; end-to-end pending) | Factsheet, AUM, expense ratio, manager, benchmark TRI, exit load, documents and distribution-adjusted return history |
| Research | NAV-derived CAGR/volatility/drawdown and ratios | Full verified historical NAV, calendar returns, benchmark TRI, peer context and methodology UI |
| Compare | Scheme-code based comparison | Like-for-like plan/option/benchmark/category validation and charts |
| Portfolio | Create/list, valuation, statement preview/import, manual BUY/SELL, transaction history, audited void, holdings breakdown, cost basis, realized/unrealized/total gain-loss, conditional XIRR, scheme concentration bars and consolidated multi-portfolio overview (this PR; end-to-end pending) | Asset-class/sector exposure, cashflow attribution and tax/exit-load-aware performance |
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

- CI run #545 passed SQLite and PostgreSQL migrations/tests, lint, JavaScript syntax checks and dashboard/research DOM/layout contracts on commit `b8402391a7f845497006ff0affae9685c1fd518d`. A no-tree-change commit was pushed afterward to queue a final push-triggered run.
- CI success proves only the commit and tests actually run in CI; it does not prove live Supabase settings, SMTP delivery or real browser sign-up.
- Setting Render environment variables triggers a deployment but does not prove that the expected commit is live.
- No test account was created and no production portfolio/NAV records were modified for this audit.
- CI run #535 passed SQLite and PostgreSQL tests and JavaScript syntax checks on commit `1b4e465fa7f83f6763b4de0e32b2f8d93d4a5c43`. A subsequent one-line rounding refinement to per-holding P/L is not included in that run. Live browser verification is still required before merge/deploy.


## Monthly and category-relative fund rankings

- The Fund Screener exposes 1M, 3M, 6M, 1Y, 3Y and 5Y NAV-only return columns when the selected research window contains sufficient history.
- Each screener row includes a rank within the same stored scheme group, sub-category, plan and option, alongside the global filtered rank.
- The Monthly Category Leaders endpoint ranks completed calendar-month returns by broad SEBI scheme group and exposes prior-month within-subcategory rank movement.
- Calendar-month comparisons use actual observed NAV values only; no weekend/holiday interpolation or dividend adjustment is performed.
- The Research UI provides five broad SEBI group leaderboards with month, Direct/Regular and Growth/IDCW selectors.
- Monthly leaderboards require a refreshed 365-day research snapshot containing monthly return history. Existing snapshots predate this field and remain readable; refresh is required to populate the new monthly cards.


## Automatic research snapshot refresh

- After a successful daily AMFI NAV ingestion commits, the service rebuilds the precomputed research snapshots used by Fund Screener and monthly category leaderboards.
- A research snapshot rebuild failure is reported as `deferred` in the NAV refresh response and does not roll back accepted NAV ingestion.
- Operator logs record the safe failure class and rebuild counts; no credentials or NAV payloads are logged.
- The operator can still run the explicit snapshot refresh endpoint independently.


## First-visit research snapshot bootstrap

- If an authenticated user opens Fund Screener while the shared research snapshot cache is empty, the API builds the precomputed rankings from accepted NAV observations once and then serves the screener.
- A process-local lock prevents concurrent first-visit requests from starting duplicate builds.
- The UI waits for the screener bootstrap to finish before requesting the five monthly category leaderboards.
- If bootstrap is already in progress or fails, the API returns a retryable 503 rather than displaying fabricated ranks.
