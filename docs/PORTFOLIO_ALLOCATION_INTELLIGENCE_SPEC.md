# Portfolio Allocation & Strategy Intelligence — Product Specification

Status: **Design baseline / implementation required**  
Target branch: `audit/production-foundation`  
Scope: owner-scoped mutual-fund portfolio intelligence; read-only analysis and non-executable recommendations.

## 1. Product principle

Do not build another returns dashboard. Build a portfolio decision-support system that answers:

1. What do I own, through direct fund units and underlying look-through?
2. What risks and concentrations am I actually exposed to?
3. Where does my current portfolio differ from my own target allocation and risk budget?
4. What should the next SIP / lump-sum contribution prioritise, given those gaps?
5. How has the portfolio and the quality of its underlying data changed since the previous review?

The system must explain every important result with its formula, data date, source, coverage, assumptions and limitations. It must never turn missing data into zero or present an estimate as a verified fact.

## 2. Reference-report concepts to retain and improve

The October 2026 TWT report provides five useful starting concepts:

- Fund and segment allocation, including each fund's share inside its segment.
- Actual market-cap exposure from underlying holdings, not merely scheme category labels.
- Pairwise fund overlap using common securities.
- AMC-level portfolio concentration.
- A market-condition-aware SIP top-up framework.

Keep these concepts, but make the calculations portfolio-weighted, source-provenanced, target-aware and reproducible. The report's illustrative thresholds (for example, overlap bands, AMC concentration bands and SIP multipliers) are not universal rules and must not be hard-coded as recommendations.

## 3. Existing foundation to reuse

The candidate application already contains important foundations:

- Transaction-ledger valuation and audited transaction corrections.
- Verified, immutable, source-hashed holdings disclosures with ISIN matching.
- Pairwise overlap endpoint using the sum of the minimum positive weights for common ISINs.
- Portfolio holdings look-through with fresh/stale/missing disclosure coverage.
- Security concentration metrics (HHI, effective security count, top-1/5/10 weights and ISIN identity coverage).
- Historical portfolio risk estimates, custom sensitivity stress, goals, rebalance preview and immutable report snapshots.

Extend these capabilities. Do not create duplicate ingestion pipelines or a second portfolio ledger.

## 4. Intelligence modules

### 4.1 Portfolio composition and allocation map

Produce independent views for:

- Scheme / fund weight in total portfolio.
- Scheme-category and sub-category allocation.
- Asset-class allocation (equity, debt, hybrid, commodity, cash/other) only where the source classification is verified.
- Underlying market-cap exposure (large, mid, small, other/unclassified).
- Underlying sector and security exposure.
- AMC concentration.
- Investment style / factor exposure only when supported by dated constituent classifications and an explicit mapping methodology.

Every table must show value, portfolio weight, target (if configured), deviation, source date and coverage. Segment contribution within a segment must be distinguished from weight in the total portfolio.

### 4.2 Underlying market-cap classification

Do not infer the market cap of an underlying company from the mutual-fund scheme's category or from the security name.

Create an effective-dated security classification dataset with:
- Stable security identity (ISIN where available).
- Classification source and source URL.
- Classification as-of/effective date and retrieval timestamp.
- Large / mid / small / other bucket and classification version.
- Hash of the source artifact and verification status.

Market-cap look-through is publishable only when the classification source and holdings dates are sufficiently aligned. Unclassified, non-ISIN, cash, derivative and other exposures remain visible as separate buckets. Show both:
- exposure as a percentage of the complete portfolio; and
- distribution within the classified equity exposure.

Never renormalise a partial subset to 100% without explicitly labelling it as a covered-subset view.

### 4.3 Fund overlap and duplication

Retain the existing pairwise overlap formula:
For each common valid ISIN, contribution = min(weight in fund A, weight in fund B); pairwise overlap = sum of contributions.

Add portfolio-level overlap intelligence:
- Full pairwise matrix for funds actually held.
- Common-stock count and top shared securities.
- Per-fund matched-ISIN coverage and disclosure dates.
- Weighted duplication contribution based on the portfolio's current fund weights.
- Top underlying securities' total portfolio contribution across all funds.
- Cluster view for funds that repeatedly own the same underlying securities.

Do not call holdings overlap "correlation". Holdings overlap, return correlation and common factor exposure are different metrics and must be shown separately.

For a pair A/B, show the symmetric matched overlap as well as each fund's shared exposure. For portfolio-level duplication, define and document a non-double-counting aggregation method; do not simply average pairwise overlap percentages. Include a worked test fixture with three funds and overlapping holdings before release.

### 4.4 AMC concentration

Calculate AMC exposure from current portfolio market value, not from the count of schemes.

Show:
- AMC amount and total-portfolio weight.
- AMC rank, month-on-month change and target/band deviation.
- Top-1, top-3 and top-5 AMC concentration.
- HHI and effective number of AMCs.
- AMC exposure contributed indirectly through all underlying schemes held.

Keep scheme-house concentration separate from underlying-company concentration. AMC limits are user-configurable; do not enforce the report's 35% / 40–45% examples as universal limits.

### 4.5 Target allocation and drift engine

Allow user-defined target ranges at multiple levels:
- Asset class.
- Market-cap bucket.
- Scheme category.
- AMC.
- Individual scheme.
- Sector / factor where classification coverage is adequate.

Each target has minimum, preferred target, maximum, effective date and optional priority. Validate that mutually exclusive target groups reconcile to 100% where appropriate.

For each dimension calculate:
- Actual weight.
- Target weight and allowed band.
- Absolute drift in percentage points.
- Relative drift versus target.
- Amount required to reach target at current portfolio value.
- Status: within band / watch / underweight / overweight / data insufficient.
- Whether the deviation is actionable through contributions alone.

Never recommend a trade from an incomplete valuation or insufficient look-through coverage.

### 4.6 Contribution-first SIP and lump-sum planner

The next-contribution planner should optimise new money before suggesting sells:

1. Check valuation and NAV freshness.
2. Check holdings-disclosure and classification coverage.
3. Identify target-allocation gaps.
4. Penalise additional contributions to breached AMC, scheme or security concentration limits.
5. Account for overlap / duplication and risk-budget constraints.
6. Allocate the proposed contribution to the highest-priority eligible gaps.
7. Show the before/after allocation and residual drift.

Output a transparent allocation proposal, not an instruction or auto-executed transaction. Provide a reason for each suggested allocation and identify which constraints prevented an allocation.

A sell/rebalance path is a separate preview and must surface tax-lot, exit-load, transaction-cost and scheme-restriction data gaps. Until those inputs are verified, show a gross indicative estimate only and state the omissions.

### 4.7 Smart SIP / market regime engine

Do not use "below all-time high" or a coloured dot as a standalone valuation signal.

Build a configurable, explainable regime model using only available, dated, source-backed data:
- Benchmark TRI drawdown from rolling 52-week / 3-year highs.
- Trend and momentum over explicitly defined windows.
- Volatility regime.
- Relative valuation (for example, PE/PB) only if a reliable, licensed/official source and consistent history are available.
- Portfolio allocation gap and risk budget.
- User's emergency cash / liquidity constraints if the user chooses to provide them.

Separate two independent decisions:
- **Portfolio need:** is this asset class / segment under target?
- **Market opportunity:** does the configured market-regime rule permit a tactical top-up?

A top-up is eligible only when data quality is acceptable and user-configured limits allow it. The default behaviour is to continue the planned SIP; no multiplier is applied automatically. Show the exact signal inputs, threshold version, status, confidence/coverage and reason. Missing valuation data must say "not assessed", not "overvalued" or "undervalued".

### 4.8 Risk and resilience

Reuse the existing historical risk engine and expand only with defensible data:
- Volatility, downside deviation, Sharpe / Sortino with visible assumptions.
- Maximum drawdown and recovery duration where history permits.
- Historical VaR / CVaR and worst 1/5/21-day periods.
- Fund and portfolio return correlation matrix, with common-date coverage.
- Concentration risk from underlying security, sector, AMC and scheme.
- User-defined scenarios and transparent scenario contribution attribution.
- Goal-level shortfall / probability analysis only when assumptions and model are explicit; do not label deterministic projections as probabilities.

Show NAV history coverage, lookback dates, missing observations, stale inputs and the fixed-current-weight limitation next to every risk output.

### 4.9 Monthly change intelligence

Create month-end snapshots and compare them with the prior valid snapshot:
- Allocation changes in percentage points and rupees.
- New / exited schemes and changed weights.
- Market-cap, sector, AMC and top-security concentration changes.
- Overlap changes, with disclosure dates on both sides.
- Risk metric changes using comparable windows.
- Target breaches opened / resolved.
- NAV and holdings data-quality changes.
- Contributions, withdrawals and market movement separated where transaction history permits.

Do not attribute a change to market performance when flows, missing disclosures or classification changes could explain it. Mark non-comparable periods explicitly.

## 5. Data quality and publication gates

Every metric response must carry a common evidence envelope:

- `calculated_at` and portfolio valuation as-of date.
- Source identifiers, source URLs, hashes and source as-of dates.
- NAV freshness and holdings-disclosure freshness.
- Covered market value / total market value.
- ISIN identity coverage.
- Missing, stale, unclassified and excluded exposure.
- Methodology identifier and version.
- Warnings and reasons a metric is withheld.

Suggested configurable publication gates (not universal investment rules):
- Portfolio valuation must be complete and NAVs within the configured staleness limit.
- Market-cap / sector views must show their covered-weight percentage and must not imply completeness below the user's chosen threshold.
- Overlap must show both disclosure dates and ISIN coverage for each fund.
- A recommendation must be withheld when its required inputs are stale, missing or inconsistent.

Metric states should be explicit: `AVAILABLE`, `PARTIAL`, `STALE`, `WITHHELD`, `NOT_CONFIGURED`. Never replace these with zero.

## 6. Dashboard experience

Add a Portfolio Intelligence workspace with these sections:

1. **Executive diagnosis** — portfolio value, valuation status, target fit, largest concentration, top risk flags and data-confidence status.
2. **Allocation map** — fund/category/asset class/market cap/sector/AMC views with drill-down.
3. **Overlap lab** — pairwise heatmap, common securities, portfolio-weighted duplication and coverage.
4. **Risk lab** — historical risk, correlation, concentration and scenario analysis.
5. **SIP & rebalance planner** — contribution-first allocation, before/after preview, blocked constraints and optional trade preview.
6. **Monthly review** — month-on-month movement and downloadable immutable report.
7. **Methodology & data health** — formulas, source lineage, dates, exclusions, warnings and confidence.

Use consistent definitions across dashboard, API, exports and PDF. Every chart must expose its underlying table and date/coverage context.

## 7. Proposed API surface

Reuse existing endpoints and add versioned, owner-scoped endpoints only where needed:

- `GET /v1/portfolios/{id}/allocation`
- `GET /v1/portfolios/{id}/overlap-matrix`
- `GET /v1/portfolios/{id}/concentration`
- `GET /v1/portfolios/{id}/allocation-drift`
- `POST /v1/portfolios/{id}/contribution-plan/preview`
- `GET /v1/portfolios/{id}/monthly-review`
- `GET /v1/portfolios/{id}/intelligence/health`

API outputs must be deterministic for the same inputs and methodology version. All private endpoints must enforce verified user ownership. No browser endpoint may expose operator credentials or invoke ingestion.

## 8. Testing and acceptance criteria

### Calculation tests
- Fund weights and segment weights reconcile; rounding does not hide residuals.
- Market-cap exposure reconciles to classified, unclassified and other exposure.
- Effective-dated security classifications choose the correct as-of version.
- ISIN duplicates aggregate deterministically; non-ISIN rows never cross-match.
- Pairwise overlap is symmetric and bounded by each fund's matched positive exposure.
- Portfolio duplication fixture proves the aggregation is not a naive average or double-counted total.
- AMC weights use market values and reconcile to the covered portfolio.
- HHI and effective-count calculations handle empty, single-name and highly concentrated portfolios.
- Drift and contribution plans respect min/target/max bands and all concentration caps.
- SIP regime output is deterministic, threshold-versioned and withheld on stale/missing inputs.
- Monthly comparisons distinguish flow, market movement, source refresh and classification changes where possible.

### Data / security tests
- Missing or stale NAV, incomplete valuation, missing holdings and low ISIN coverage never become zero exposure.
- Only VERIFIED disclosures are used.
- Every metric includes source lineage and as-of dates.
- Two-user isolation covers all new endpoints and stored target configurations.
- User cannot read or mutate another user's targets, plans, snapshots or reports.
- No recommendation endpoint executes a transaction.
- Inputs are bounded; malformed percentages, duplicate targets and non-finite numbers are rejected.

### Product acceptance
- User can configure target ranges and change them without code edits.
- Every warning explains what triggered it and how to resolve it.
- Every recommendation explains why it was selected and what constraint limited it.
- Dashboard, PDF and API use the same metric values and methodology version.
- A report can be regenerated from its immutable snapshot without silently fetching newer data.
- CI covers PostgreSQL and SQLite-compatible calculation paths; production deployment remains separately gated.

## 9. Delivery sequence

### P0 — Trustworthy foundations
1. Audit existing allocation, look-through, overlap, concentration and report code for gaps and denominator consistency.
2. Add a shared metric evidence envelope and methodology versioning.
3. Add portfolio-level allocation and AMC concentration from verified current valuations.
4. Add portfolio-wide overlap matrix with coverage and a tested non-double-counting aggregate.
5. Add owner-scoped target bands and allocation drift.
6. Add contribution-first preview with hard data-quality and concentration gates.

### P1 — Better risk and market context
1. Effective-dated market-cap/security classification source pipeline.
2. Return-correlation and recovery-duration analytics.
3. Benchmark TRI-based market regime inputs and versioned Smart SIP rules.
4. Monthly comparable snapshots and change attribution.

### P2 — Advanced intelligence
1. Factor/style and debt-quality/duration exposure where source coverage supports it.
2. Scenario library and risk-budget-aware contribution planner.
3. Tax-aware rebalance preview after reliable tax and exit-load metadata integration.

## 10. Safety and release boundary

This is educational decision support, not personalised regulated investment advice. The system must not promise returns, label a fund "best" from one metric, infer suitability from age or risk appetite alone, or automatically buy/sell/rebalance. Recommendations remain previews requiring user review.

This specification does not authorise a production deploy, schema migration, secret change or production data write. All implementation work must remain on the candidate branch until the existing P0 release gates, branch reconciliation, backup/restore evidence and explicit release approval are complete.
