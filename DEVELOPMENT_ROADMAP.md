# MF Terminal Intelligence — Development Roadmap

Last reviewed: 2026-11-11
Repository: `yashvyas638/mf-terminal-intelligence-backend`
Authorised branch: `audit/production-foundation`
Product structure: **P0–P6** (seven gated phases)
Product north star: a premium, source-grounded Indian mutual-fund research and portfolio intelligence terminal.

## How this roadmap is used

This is the single phase-control document. Detailed product requirements live in:
- [Product Blueprint](docs/PRODUCT_BLUEPRINT.md)
- [Engineering Playbook](docs/ENGINEERING_PLAYBOOK.md)
- [Architecture and Data Model](docs/ARCHITECTURE_AND_DATA_MODEL.md)
- [UX and Design System](docs/UX_AND_DESIGN_SYSTEM.md)

Every feature must be linked to a phase, an acceptance test and a commit. No phase is complete because code was written; it is complete only when the relevant evidence is recorded here and sign-off is explicitly granted.

## Phase map

| Phase | Objective | User outcome | Status |
|---|---|---|---|
| **P0** | Infrastructure, security, NAV reliability, data integrity and portfolio import | Trustworthy, secure, operational foundation and accurate baseline portfolio | **OPEN — BLOCKED** |
| **P1** | Fund research, historical performance, rolling returns and risk metrics | Understand fund quality, consistency, risk and performance against fair peers/benchmarks | NOT STARTED |
| **P2** | Holdings overlap, regression and quantitative research | Understand underlying exposures, concentration, correlations and quantitative relationships | NOT STARTED |
| **P3** | Macro intelligence and stress testing | Understand economic regimes and portfolio sensitivity under historical/hypothetical shocks | NOT STARTED |
| **P4** | Portfolio optimisation and Decision Centre | Evaluate portfolio changes with transparent evidence, constraints and trade-offs | NOT STARTED |
| **P5** | Tax, wealth projections, monitoring and reports | Understand after-tax outcomes, future ranges, goals and portfolio changes | NOT STARTED |
| **P6** | AI research assistant and production hardening | Ask source-grounded questions and operate a secure, monitored, recoverable product | NOT STARTED |

Dependencies are sequential. A later phase may have design notes prepared early, but implementation must not bypass unresolved upstream data, security or correctness gates.

## Standard end-to-end execution flow

```text
Idea / user problem
  → Phase and scope assignment
  → Acceptance criteria + non-goals
  → Inspect branch, code, schema, tests and deployment
  → Design data flow, threat model and failure handling
  → Implement smallest coherent change
  → Unit + integration + PostgreSQL + migration + UI tests
  → Diff review (correctness/security/performance/compatibility)
  → Commit on authorised branch
  → Push and verify remote SHA
  → CI green on exact SHA
  → Staging database migration and reconciliation
  → Render deploy of approved SHA
  → Production smoke tests and monitoring
  → Update evidence log and rollback reference
  → Phase sign-off
```

Mandatory order: **DEFINE → INSPECT → DESIGN → DEVELOP → TEST → REVIEW → COMMIT → PUSH → CI → DATABASE → DEPLOY → SMOKE TEST → RECORD → SIGN OFF**.

## P0 — Infrastructure, security, NAV reliability, data integrity and portfolio import

**Target outcome:** a dependable foundation. No advanced analytics are trusted until this phase passes.

### Build scope
1. **Repository and delivery controls**
   - Confirm remote, branch, exact commit and PR state before every change.
   - Add phase docs, code ownership/review conventions, CI and release evidence.
   - Verify local working tree via actual local `git status`; remote GitHub cannot prove local cleanliness.
2. **Runtime and secrets**
   - Pin/verify Python runtime and dependencies.
   - Validate production PostgreSQL URL and reject SQLite in production.
   - Rotate exposed credentials; store only in Render/GitHub secret stores.
   - Keep logs redacted; never print URLs, passwords, API keys, tokens or financial statement contents.
3. **Database and security**
   - Inspect live Supabase tables, columns, indexes, constraints, triggers, extensions, grants and RLS.
   - Reconcile live schema against every Alembic migration.
   - Use Alembic as the only production schema manager; no production `create_all`.
   - Design user/tenant ownership and RLS before multi-user portfolio exposure. Shared API key is not user authorization.
   - Backups, restore drill, least privilege, rate limits and audit.
4. **AMFI pipeline**
   - Fetch official source with timeouts, retries, content-type/body checks and bounded size.
   - Preserve source hash, retrieval time, NAV effective date and parser version.
   - Parse/normalise; validate scheme code, ISIN, name, positive finite Decimal NAV and date.
   - Quality gate for minimum records, stale/future dates, duplicates, malformed rows, distribution anomalies and source format changes.
   - Persist transactionally only after validation.
   - Exact replay is idempotent; missing ISIN never fabricated; later missing marker must not erase a known identifier.
   - NAV correction must preserve previous value/source in append-only revision history.
   - Daily NAV feed is not a historical backfill; state coverage honestly.
5. **Portfolio import and ledger**
   - CSV upload preview, column mapping, duplicate detection, scheme resolution, row-level validation and reconciliation.
   - User confirmation before atomic commit.
   - Immutable transaction facts with audited void/correction, no hard delete.
   - Decimal arithmetic, oversell prevention, ownership checks and missing-NAV-aware valuation.
6. **Dashboard baseline**
   - Home/data health, fund search, NAV status/history and portfolio import/valuation.
   - Loading, empty, stale, partial, error and success states.

### P0 acceptance criteria
- [ ] Actual remote branch and local working tree status recorded.
- [ ] Full live Supabase schema, indexes, constraints, grants and RLS inspected and documented.
- [ ] PostgreSQL CI passes independently of SQLite.
- [ ] Alembic upgrade from empty DB and prior supported revision passes on PostgreSQL.
- [ ] No production startup schema mutation; migrations are authoritative.
- [ ] Live AMFI response fetched and parser validated with timestamp, source hash and record counts.
- [ ] Invalid/HTML/empty/stale/future/malformed feed is rejected without changing accepted data.
- [ ] Exact duplicate replay creates no duplicate rows.
- [ ] Missing ISIN and duplicate behavior verified against parser and DB integration tests.
- [ ] NAV correction preserves previous values and source provenance.
- [ ] Historical coverage limitation is explicit; no fabricated NAV history.
- [ ] Portfolio import preview, reconciliation, atomic commit, duplicate handling and rollback tested.
- [ ] Portfolio ownership/RLS isolation tests pass before multi-user access.
- [ ] Render deploy commit exactly matches approved SHA; environment metadata verified without exposing secrets.
- [ ] Production AMFI → API → Supabase → dashboard/portfolio read path smoke-tested.
- [ ] Last known-good Render deploy ID/SHA and recovery procedure documented.
- [ ] No unresolved critical/high security or data-integrity defects.

### P0 do not
- Never reset, truncate, drop or bulk rewrite production tables as a test.
- Never run a destructive migration without explicit approval and verified backup/restore.
- Never lower production AMFI minimum-record threshold to bypass a failed feed.
- Never treat successful SQLite CI as PostgreSQL or production proof.
- Never expose a shared service API key in browser code as multi-user security.
- Never silently overwrite NAV correction history, guess scheme identity or hide missing data.
- Never auto-commit imported statements without preview/reconciliation/user confirmation.
- Never deploy an unverified SHA or merge to main without approval.

### Current P0 evidence and blockers
- Earlier code commit `3ca12c92a717da5bdda79911e793483d6a376ac9` passed SQLite migration, Ruff and 15 pytest tests (CI run `43020514070`, job `130522253718`). This does not establish PostgreSQL compatibility.
- Subsequent branch commits listed in the prior evidence log include NAV correction provenance, lifespan migration, parser hardening, PostgreSQL CI, missing-ISIN preservation and live-source validation workflow. Their exact latest CI result and production state must be re-verified on current branch head before relying on them.
- Current source review identified that portfolio tables lack user/tenant ownership. Do not enable multi-user use until isolation is designed and tested.
- Live Supabase schema/RLS and Render deployment record remain unverified.
- Last known-good production deployment SHA/deploy ID remains UNKNOWN until Render history is inspected.
- Local working-tree cleanliness remains UNKNOWN unless a local Git status result is provided.
- No destructive production operation is authorised.

## P1 — Fund research, historical performance, rolling returns and risk metrics

**Target outcome:** a reliable fund research workstation.

### Build
- Canonical fund identity: AMC, scheme code, ISIN, category, plan, option, benchmark, inception and lifecycle.
- Fund facts: AUM, expense ratio, exit load, manager, minimums, factsheet/SID/KIM and publication/as-of dates.
- Direct vs regular; growth vs IDCW; do not compare unlike variants as equivalent.
- NAV history coverage, gaps, corrections and distribution caveats.
- Absolute return, CAGR, XIRR when cashflows exist, calendar returns, rolling returns, benchmark-relative returns.
- Volatility, downside deviation, Sharpe, Sortino, beta, alpha, tracking error, information ratio, max drawdown, recovery time, capture ratios and consistency.
- Category/peer comparison with sample size, peer-universe definition and survivorship caveats.
- Fund profile, compare view, watchlists, methodology drawer and exportable research brief.

### Do not
- Do not call NAV CAGR total return if IDCW/distributions are not included.
- Do not compare different plans/options/benchmarks/periods without clear disclosure.
- Do not calculate alpha/beta/Sharpe without benchmark alignment, risk-free assumption, frequency and adequate observations.
- Do not interpolate missing NAV data or fabricate history.
- Do not rank solely on trailing return or opaque composite scores.

### Exit
- Independent calculation fixtures and benchmark alignment tests pass.
- Rolling-window, short-history, missing-observation and data-gap behavior is explicit.
- Every metric shows period, source, as-of date, frequency, formula version, assumptions and coverage.

## P2 — Holdings overlap, regression and quantitative research

**Target outcome:** look-through intelligence that reveals hidden portfolio exposures.

### Build
- Dated AMC holdings/factsheet ingestion with provenance.
- Security master and ISIN/ticker/issuer mapping with confidence and unmatched queue.
- Stock, sector, market-cap, style and group exposure.
- Fund-to-fund overlap, weighted overlap, concentration and top contributors.
- Portfolio look-through and duplicate exposure.
- Correlation/covariance matrices, rolling correlation, regression, factor sensitivity and residual diagnostics.
- Scenario/backtest lab with explicit rebalance, costs, benchmark and data availability.

### Do not
- Do not compare holdings from different effective dates as simultaneous.
- Do not map securities on name alone when ambiguous.
- Do not imply regression proves causality.
- Do not backtest with look-ahead/survivorship bias or unavailable historical holdings.
- Do not show model fit without sample size, residuals and diagnostics.

### Exit
- Holdings freshness and identity-match confidence visible.
- Overlap and regression calculations independently validated.
- Look-ahead, stale holdings, unmatched securities and missing-data tests pass.

## P3 — Macro intelligence and stress testing

**Target outcome:** transparent understanding of macro exposures and possible portfolio sensitivity.

### Build
- RBI policy, rates/yields, inflation, liquidity, INR, crude, gold, global equity and bond indicators.
- India/US policy calendar, release dates and source-linked event timeline.
- Macro regime labels with explicit thresholds and uncertainty.
- Portfolio exposure mapping to sectors, factors, duration, currency and geography.
- Historical scenario replay and hypothetical stress tests.
- Base/upside/downside ranges and impact journal.

### Do not
- Do not present correlation as causation.
- Do not forecast central-bank or market outcomes with certainty.
- Do not confuse release date with observation/effective date.
- Do not label stress tests as predictions or turn headlines into unverified trade signals.

### Exit
- Source freshness/revision policy documented.
- Each scenario lists shock, horizon, mapping, assumptions and limitations.
- Deterministic scenario fixtures and alert tests pass.

## P4 — Portfolio optimisation and Decision Centre

**Target outcome:** evidence-led, user-approved portfolio change analysis.

### Build
- Current vs target allocation across funds, categories, AMCs, sectors, asset classes and risk.
- ADD / HOLD / REDUCE / SWITCH / EXIT research cases with evidence and counter-evidence.
- Portfolio constraints, minimum/maximum weights and concentration limits.
- Risk-aware optimisers plus simple robust alternatives.
- SIP contribution planning and allocation.
- Rebalance preview with drift, units, cash impact, taxes, exit loads and minimums.
- Decision log with thesis, source evidence, assumptions, user approval, review date and outcome.
- What-if and opportunity-cost analysis.

### Do not
- Do not auto-trade.
- Do not present optimiser output as certainty or advice.
- Do not ignore tax, exit loads, lock-ins, liquidity, restrictions or user constraints.
- Do not overwrite user targets or decisions without confirmation.

### Exit
- Deterministic calculations and infeasible-constraint handling tested.
- Rebalance reconciles to portfolio/cash and shows all assumptions.
- Decisions and approvals are auditable.

## P5 — Tax, wealth projections, monitoring and reports

**Target outcome:** explain after-tax outcomes and long-term scenarios with reproducible assumptions.

### Build
- Tax lots, holding periods, realised/unrealised gains and effective-dated tax rules.
- Capital gains, tax harvesting candidates and exit-load schedules.
- SIP step-up, goal planning, inflation-adjusted target and required contributions.
- Deterministic projections and Monte Carlo ranges.
- Wealth snapshots, cashflows, milestones and attribution.
- Alerts for stale data, allocation drift, fund events, concentration, lock-ins and goal progress.
- PDF/Excel/CSV reports with as-of dates and methodology.

### Do not
- Do not hardcode tax rules without effective dates and authoritative sources.
- Do not describe projections or Monte Carlo percentiles as guaranteed.
- Do not create noisy/panic alerts or rewrite historical snapshots/reports.

### Exit
- Tax fixtures reviewed against effective-dated rules.
- Projection results reproducible from saved assumptions.
- Alert thresholds configurable and exports reconcile to source data.

## P6 — AI research assistant and production hardening

**Target outcome:** a source-grounded research copilot and a secure, monitored, recoverable production product.

### Build
- Retrieval-grounded answers over verified metrics and official source documents.
- Citations with source timestamp, document version and coverage/confidence.
- Fund, portfolio and macro research briefs.
- Natural-language analytics with visible filters/formulas and deterministic calculation services.
- Explain what changed, why it matters, counter-evidence and uncertainty.
- Threat model, tenant isolation, role-based access, audit, rate limiting and privacy controls.
- Job queue/locks, retries, observability, backup/restore, disaster recovery and performance tests.
- Accessibility, mobile/tablet/desktop QA, onboarding, help and product analytics.
- Full regression and operational handover.

### Do not
- Do not let an LLM invent metrics or citations.
- Do not let AI run arbitrary write SQL or modify portfolio records.
- Do not send sensitive financial data to external models without explicit consent and approved controls.
- Do not hide uncertainty, contradictory sources or missing evidence.

### Exit
- AI answers are grounded, cited and reproducible.
- Security/privacy/tenant isolation tests pass.
- Backup restore and failure recovery demonstrated.
- Full regression, load, accessibility and device tests pass.
- Operational ownership and support runbooks complete.

## Global definition of done

For every phase:
- scope and non-goals are written
- data contracts and failure modes reviewed
- unit/integration/PostgreSQL tests pass
- migration is reviewed and rehearsed where applicable
- security/privacy and authorization reviewed
- UI loading/empty/stale/partial/error/success states work
- exact branch SHA and CI run recorded
- production deploy SHA verified where applicable
- smoke tests and reconciliation recorded
- rollback target and recovery plan recorded
- limitations and unresolved issues listed
- explicit phase sign-off recorded

## Release and rollback record

- Authorised branch: `audit/production-foundation`.
- Never merge to `main` without explicit approval.
- Candidate commit from earlier P0 review: `3ca12c92a717da5bdda79911e793483d6a376ac9`.
- Last known-good production commit: **UNKNOWN until Render deployment history is inspected**.
- Last known-good Render deploy ID/time: **UNKNOWN**.
- Rollback: redeploy exact last successful Render deployment; verify health, DB reachability, auth and core read endpoints. Do not run Alembic downgrade as routine rollback. Use forward-fix or an approved, tested backup restore for schema/data issues.

## Evidence log

### 2026-11-11
- Earlier commit `3ca12c9`: CI run `43020514070`, job `130522253718`; SQLite migration, Ruff F/B and pytest passed (15 tests, 3 warnings).
- Feature-branch follow-up commits listed in prior roadmap revision include NAV correction provenance, lifespan migration, AMFI payload hardening, PostgreSQL 16 CI, missing-ISIN preservation, live-source validation workflow and tenancy-boundary documentation. Verify exact latest SHA and CI before treating as passed.
- Product/engineering documentation added: Product Blueprint, Engineering Playbook, Architecture and Data Model, UX and Design System.
- P0 remains OPEN. Supabase live catalog/RLS, Render deployed SHA, local working-tree status, end-to-end production test and last known-good deployment remain unverified.


## 2026-11-11 — Live Supabase security evidence update

- User-provided live inspection: all eight public tables reported RLS disabled; the policy query returned no rows.
- User-provided grants inspection showed privileges assigned to Supabase roles `anon` and `authenticated`; SQL Editor session role was `postgres`.
- Live Alembic revision reported as `0003_nav_correction_history`.
- Confirmed portfolio schema has no owner/tenant column. Multi-user access remains prohibited.
- Added migration `0004_restrict_supabase_client_roles` to revoke existing table/sequence/function privileges and future default privileges from `anon` and `authenticated` for objects created by `postgres`. This is containment, not RLS or multi-user authorization.
- Added PostgreSQL regression test and CI role fixtures. CI run is pending for commit `735380aa16158f2d7f3ea3e737ed85034e220022`.
- Production migration is NOT approved or confirmed. First verify Render's connection role and deployment branch; do not deploy blindly.
- See [P0 Security Remediation](docs/P0_SECURITY_REMEDIATION.md) for scope, preconditions and remaining blockers.

P0 remains **OPEN — BLOCKED**. No P1 implementation, main merge, production permission change, or production deployment is authorised by this evidence update.
