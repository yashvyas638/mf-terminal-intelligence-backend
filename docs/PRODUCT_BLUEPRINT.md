# MF Terminal Intelligence — Product Blueprint

## Product north star

Build a research-grade Mutual Fund Intelligence Terminal for Indian investors. It should turn trusted source data into explainable fund research, portfolio understanding, scenario analysis, and documented decisions.

The product is not a broker, order router, guaranteed-return engine, or personalised investment-advice substitute. No trade is executed. Every analytical output must disclose its data date, source, methodology, assumptions, coverage, and limitations.

## Product principles

1. **Trust before intelligence:** no advanced insight on stale, incomplete, unvalidated, or mismatched data.
2. **Explain every number:** show formula/methodology, dates, benchmark, assumptions, and missing-data warnings.
3. **One source of truth:** canonical scheme identity and versioned source records; do not duplicate fund facts across modules.
4. **Historical integrity:** preserve original snapshots and record corrections; never silently rewrite financial history.
5. **Portfolio-first navigation:** users should move from their holdings to fund, category, benchmark, risk, macro, and action context.
6. **Decision support, not autopilot:** recommendations are transparent previews with reasons, counterarguments, uncertainty, tax/exit-load caveats, and user approval.
7. **Progressive disclosure:** concise dashboard first; deep tables, charts, formulas, and source evidence on demand.
8. **Fast and calm:** responsive, keyboard-friendly, accessible, low-clutter interface; no visual noise or fake precision.
9. **India-first:** INR, Indian financial year, Indian tax rules, AMFI/SEBI/AMC sources, IST timestamps; international context is clearly labelled.
10. **No silent failures:** show stale data, partial coverage, failed imports, unsupported metrics, and background-job errors explicitly.

## Information architecture

Primary navigation:
- **Home / Command Centre:** portfolio pulse, data health, important changes, upcoming events, latest research.
- **My Portfolios:** holdings, transactions, performance, allocation, goals, family/personal separation if configured.
- **Fund Explorer:** search, filters, category/AMC, plan/option, benchmark, fund profile.
- **Fund Research:** returns, rolling returns, risk, consistency, drawdowns, manager, costs, documents.
- **Compare:** side-by-side funds with like-for-like period, category, benchmark, plan and data coverage.
- **Portfolio X-Ray:** underlying holdings, sector/stock exposure, overlap, concentration, factor and risk contribution.
- **Market & Macro:** rates, inflation, currency, liquidity, equity/bond regimes, event timeline and portfolio sensitivity.
- **Decision Centre:** ADD / HOLD / REDUCE / SWITCH / EXIT research cases, target allocation, tax/exit-load checks, action log.
- **Tax & Goals:** realised/unrealised gains, lots, holding periods, projections, goal tracking and tax reports.
- **AI Research Desk:** source-linked Q&A, fund/portfolio/macro briefs and report builder.
- **Data & Settings:** source health, imports, corrections, jobs, audit, security, user preferences.

## Phase map and user-visible outcomes

### P0 — Foundation, security, NAV reliability and portfolio data
**Outcome:** a dependable platform with secure access, safe persistence, repeatable ingestion, validated portfolio imports, and a working baseline dashboard.

Build:
- Production PostgreSQL/Supabase schema and migration discipline.
- Environment/secret validation, API auth, ownership model, least privilege, backups and audit trail.
- AMFI feed fetch, parser, quality gate, idempotent ingestion, correction provenance, historical data policy.
- Scheme master identity and ISIN normalisation.
- Portfolio creation, CSV import preview, validation, reconciliation, transaction ledger, audited corrections.
- Data health panel, import status, portfolio overview, empty/loading/error states.
- PostgreSQL CI, migration tests, live-source validation, deployment smoke tests and rollback runbook.

Do not:
- Treat SQLite CI as PostgreSQL proof.
- Run create_all as production migration management.
- expose shared service-wide API keys as multi-user authorization.
- silently overwrite NAV corrections or erase missing identifiers.
- ingest malformed, HTML, empty, stale or implausibly future-dated feeds.
- auto-import statements without preview and reconciliation.
- execute trades or modify production records as a test.

Exit:
- P0 checklist in DEVELOPMENT_ROADMAP.md is all VERIFIED with evidence.
- Supabase schema, constraints, indexes and RLS reviewed.
- PostgreSQL CI passes; Render deployed SHA matches approved branch SHA.
- live AMFI response validated and safely persisted.
- duplicate replay is idempotent; corrections have provenance; historical rows are preserved according to an approved policy.
- portfolio import, valuation and dashboard read path pass production smoke tests.
- recovery/rollback tested; no open critical/high security or data-integrity issue.

### P1 — Fund research, historical performance and risk
**Outcome:** user can research any supported mutual fund and understand its performance and risk in context.

Build:
- Canonical fund profile: AMC, scheme code, ISIN, category, plan, option, benchmark, inception, fund manager, AUM, expense ratio, exit load, minimums, factsheets/SID/KIM and source dates.
- Direct/regular and growth/IDCW mapping without accidental peer mixing.
- NAV history and corporate-action/distribution awareness; clearly label NAV-only return limitations.
- Absolute return, CAGR, XIRR where cashflows exist, rolling returns, calendar returns, benchmark-relative returns.
- Volatility, downside deviation, Sharpe, Sortino, beta, alpha, tracking error, information ratio, max drawdown, recovery time, capture ratios and consistency.
- Peer/category percentile with sample size and survivorship caveats.
- Fund compare, watchlist, filters, methodology drawer and downloadable research brief.

Do not:
- compare unlike plans, options, categories or periods without disclosure.
- call NAV CAGR total return where IDCW/distributions are not accounted for.
- publish alpha/beta/Sharpe without benchmark alignment, frequency and risk-free assumptions.
- fill missing history with fabricated/interpolated observations.
- rank funds solely by trailing return or one composite score.

Exit:
- benchmark and category mapping quality accepted.
- metrics independently tested against known fixtures and edge cases.
- rolling-window calculations, missing data, short histories and survivorship caveats verified.
- every result has source date, calculation period and methodology.

### P2 — Holdings overlap, regression and quantitative research
**Outcome:** user can see what funds really own and how exposures interact.

Build:
- AMC factsheet/portfolio holdings ingestion with effective dates and source provenance.
- Security master and identifier mapping (ISIN, ticker, issuer, exchange).
- Stock, sector, market-cap, style and group exposure.
- Fund overlap by common holdings and weighted overlap; concentration and top contributors.
- Portfolio look-through across funds; duplicate exposure and hidden concentration.
- Correlation matrix, covariance, rolling correlation, regression, factor sensitivity and residual analysis.
- Scenario/backtest lab with transparent inputs, rebalance rules, costs and benchmark.
- Holdings history and exposure-change timeline.

Do not:
- combine holdings from different dates as if simultaneous.
- map securities on name alone when identity is ambiguous.
- call overlap a risk score without explaining weights and denominator.
- imply regression proves causation.
- backtest with look-ahead bias, survivorship bias, or unavailable historical holdings.
- use a model fit without residuals, sample size and diagnostics.

Exit:
- holdings dates and sources are traceable.
- identifier mapping confidence and unmatched securities are visible.
- overlap and regression formulas independently validated.
- look-ahead, stale holdings and missing data tests pass.

### P3 — Macro intelligence and stress testing
**Outcome:** user understands which macro changes may matter to their holdings and what scenarios could do.

Build:
- RBI policy, rates/yields, inflation, liquidity, INR, crude, gold, global equity and bond indicators.
- India/US policy calendar and source-linked event timeline.
- Macro regime labels with transparent thresholds and uncertainty.
- Portfolio exposure mapping to sectors, factors, duration, currency and geography.
- Historical scenario replay and hypothetical stress tests.
- Base/upside/downside scenarios with ranges, not point certainty.
- Event impact journal and alert subscriptions.

Do not:
- present correlation as causation.
- claim to forecast central-bank actions or markets with certainty.
- mix release dates and observation dates.
- imply a stress test is a prediction.
- turn headlines into trading signals without evidence.

Exit:
- macro source freshness and revision policy documented.
- every scenario lists shocks, horizon, mapping, assumptions and limitations.
- scenario calculations tested against deterministic fixtures.
- alerts are configurable, rate-limited and auditable.

### P4 — Portfolio optimisation and Decision Centre
**Outcome:** user can evaluate portfolio changes using evidence, constraints and transparent trade-offs.

Build:
- Current vs target allocation by fund, category, AMC, sector, asset class, style and risk.
- ADD / HOLD / REDUCE / SWITCH / EXIT research cases with evidence and counter-evidence.
- Portfolio construction constraints, minimum/maximum weights and concentration limits.
- Risk-aware optimisation (mean-variance only as one option; include robust/simple alternatives).
- SIP allocation and contribution planning.
- Rebalance preview with drift, estimated units, cash impact, tax/exit-load and minimum transaction caveats.
- Decision log: thesis, evidence, date, intended action, user approval, review date and outcome tracking.
- What-if comparison and opportunity-cost analysis.

Do not:
- auto-trade.
- treat optimiser output as a recommendation without constraints and uncertainty.
- use expected returns as known facts.
- ignore taxes, exit loads, liquidity, lock-ins, minimums and user constraints.
- overwrite user targets or decisions without confirmation.

Exit:
- calculations are deterministic and independently tested.
- constraints and infeasible cases are clear.
- trade preview reconciles to holdings and cash.
- decision rationale and user approval are auditable.

### P5 — Tax, wealth projections, monitoring and reports
**Outcome:** user can understand after-tax outcomes, future scenarios and portfolio progress.

Build:
- Tax-lot accounting and holding-period engine with effective-date tax rules.
- Capital gains reports, realised/unrealised gains, tax harvesting candidates and exit-load schedules.
- SIP step-up, goal planning, inflation-adjusted target, savings rate and required contribution.
- Deterministic projections plus Monte Carlo ranges with disclosed assumptions.
- Portfolio snapshots, cashflows, wealth history, milestones and contribution attribution.
- Alerts for stale data, allocation drift, fund events, portfolio concentration, maturity/lock-in and goal progress.
- PDF/Excel/CSV reports with as-of timestamp and source/methodology notes.

Do not:
- hardcode tax rules without effective dates and authoritative source.
- describe projections as guaranteed.
- present Monte Carlo percentiles as promises.
- trigger panic alerts on small/noisy movements.
- delete historical snapshots or rewrite prior reports.

Exit:
- tax cases reviewed against effective-date test fixtures and official rules.
- projections reproducible from saved assumptions.
- alert thresholds configurable and tested.
- exports reconcile to on-screen data and carry as-of dates.

### P6 — AI Research Assistant and production hardening
**Outcome:** an explainable research copilot over the platform's verified data, with reliable operations.

Build:
- AI research desk grounded in database facts and source documents.
- Retrieval with citations, source timestamps, document version and confidence/coverage.
- Fund/portfolio/macro research briefs and comparison narratives.
- Natural-language query to structured analytics, with visible filters and formulas.
- Recommendation review: what changed, evidence, counter-evidence, assumptions and unresolved questions.
- Security hardening, tenant isolation, role-based access, audit, rate limits, abuse protection.
- Observability, job retries, queue/locks, backups, restore drills, disaster recovery and performance.
- Accessibility, mobile/tablet/desktop QA, onboarding, help, guided empty states and product analytics.
- Final regression and release sign-off.

Do not:
- let an LLM invent metrics or source citations.
- let generated SQL mutate production.
- allow AI to execute transactions or change portfolio records.
- hide uncertainty or contradictory evidence.
- send sensitive portfolio data to external models without explicit consent and approved controls.

Exit:
- AI answers are grounded, cited and reproducible.
- security/privacy threat model and tenant isolation tests pass.
- backup/restore and failure recovery are demonstrated.
- full end-to-end regression, load, accessibility and device tests pass.
- release checklist and operational ownership are complete.

## Cross-phase product quality gates

Every metric must expose:
- metric name and plain-language meaning
- formula/methodology version
- source and as-of timestamp
- calculation start/end date
- benchmark/category/peer universe where relevant
- frequency, annualisation and risk-free assumptions
- coverage count, missing observations and data-quality state
- limitations and whether result is estimated or exact

Every screen must include:
- loading, empty, partial-data, stale-data, error and success states
- clear primary action and safe cancel/back path
- responsive layout and accessible labels
- no hidden irreversible action
- consistent INR/date/number formatting

## Suggested signature experience

The Home screen should feel like a calm professional terminal:
- Top strip: portfolio value, day change (only if reliable), data freshness and last sync.
- Main canvas: allocation and performance trend with period selector.
- Research watchlist: funds with meaningful changes and why they matter.
- Risk panel: concentration, overlap, drawdown and missing-data warnings.
- Decision queue: open research cases and review dates.
- Activity timeline: imports, NAV refreshes, corrections and user decisions.

Use progressive disclosure. Do not cram every metric into the home screen.
