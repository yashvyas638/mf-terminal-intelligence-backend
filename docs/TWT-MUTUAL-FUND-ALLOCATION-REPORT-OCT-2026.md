# TWT Mutual Fund Allocation Report — October 2026 integration specification

Status: implementation specification for the isolated `ui/portfolio-intelligence` branch.
Scope: extend the existing Portfolio Intelligence workspace. This is not a second dashboard, a market-data source, or a recommendation to copy another investor's portfolio.

## Product intent

The monthly report is a repeatable portfolio review. It should explain where the portfolio is invested, what the underlying holdings add to or subtract from diversification, which exposures are concentrated, and how future contributions could move the portfolio toward a user-approved target.

The report's market commentary and SIP signal are separate from the user's portfolio allocation. A market signal must never silently override a portfolio shortfall, and a portfolio shortfall must never be presented as a market-timing signal.

## Modules and acceptance rules

### 1. Allocation snapshot

- Show current market value and weight by scheme, category/sub-category, asset class and AMC.
- Use the same frozen valuation snapshot for every chart, table and derived percentage in one report.
- Include scheme count, valuation date, NAV coverage and unclassified value/weight.
- Never infer category, asset class or market-cap classification from a scheme name. Unknown remains unknown.
- Preserve the existing portfolio allocation API and methodology version; UI must not recalculate a second, subtly different allocation.

### 2. Underlying market-cap exposure

- Calculate large-, mid- and small-cap exposure from dated underlying equity disclosures, not from the fund's marketing category.
- Include other/ cash/ debt/ international/ unclassified buckets where supported by the source data.
- Weight each underlying security by its disclosed portfolio weight and each fund by its share of the user's portfolio.
- Record disclosure as-of date, retrieval date, source, security-identity match status and coverage.
- Report both covered exposure and unknown exposure. Do not renormalise partial coverage to 100% without an explicit label.
- Market-cap classifications must be dated and source-backed. Stale or unresolved classifications are excluded from verified buckets and shown as unknown.

### 3. Fund overlap

- Compare only holdings that have verified security identity and compatible disclosure dates.
- Show pairwise overlap, common securities, each fund's contribution to the common exposure, and coverage for both funds.
- State the exact overlap definition and denominator in the UI and report. Do not mix a count-of-common-stocks metric with a portfolio-weight overlap percentage.
- Missing holdings, stale disclosures and unresolved ISINs must reduce coverage, not be treated as non-overlap.
- Keep fund-to-fund overlap separate from direct-stock overlap and from sector/market-cap similarity.

### 4. AMC concentration

- Aggregate the user's scheme market values by AMC.
- Show AMC weight, largest-AMC share, HHI and effective number of AMCs, alongside the number of schemes and unclassified AMC value.
- Alert thresholds are user-configurable policy, not a universal risk rating.
- A concentration alert is informational; it does not itself trigger a sale or switch.

### 5. Target allocation and contribution-only rebalance

- Targets are user-owned, versioned and effective-dated. Preserve prior versions for historical reports.
- Validate target bands and mutually exclusive buckets before save; total target weight must reconcile to 100% under the chosen policy.
- Show actual vs target, percentage-point drift, value gap and whether the configured band is breached.
- Default action is no action. Preview how future contributions/SIPs could reduce drift before suggesting any sale.
- The preview is simulation-only. It must not create transactions, alter SIP mandates, or issue sell instructions.
- Show the assumptions, amount, cadence, allocation constraints and residual cash in every preview.

### 6. SIP signal and market context

- Render market-state/SIP signal as an independent context panel with its own source, timestamp, rule version and evidence.
- Keep signal states (for example Green/Yellow/No signal) distinct from allocation states (underweight/within band/overweight).
- Do not multiply or increase a user's SIP automatically. Any contribution scenario must be explicitly user-entered and preview-only.
- Do not infer a market signal from allocation drift or infer allocation suitability from a market signal.

### 7. Monthly comparison and report history

- Compare month-end snapshots only when valuation and disclosure coverage are sufficiently comparable.
- Show absolute and percentage-point changes separately; explain changes caused by holdings, market movement, classification updates or coverage changes where identifiable.
- Retain immutable report snapshots with methodology version, valuation snapshot ID, disclosure dates, target-policy version and generation timestamp.
- PDF/export must reproduce the saved snapshot, not recompute using today's NAVs or today's disclosures.
- If comparable prior-period evidence is absent, say so instead of fabricating a month-on-month trend.

## Data quality and audit contract

Every derived exposure should expose: source, source as-of date, retrieval timestamp, freshness state, coverage numerator/denominator, unresolved identities, methodology version and relevant input snapshot IDs.

A report is not "complete" merely because an endpoint returned HTTP 200. Partial data must remain visibly partial. Unknown is not zero. A later refresh may create a new report, but must not rewrite a previously saved report.

## UI placement

Use the existing Portfolio Intelligence tabs and endpoints:
- Allocation: scheme/category/AMC allocation, target bands, drift and contribution preview.
- Look-through: fund overlap and underlying market-cap/sector exposure with coverage.
- Monthly review: immutable month snapshots, comparable period deltas and PDF export.

Avoid a duplicate dashboard or a second independent calculation engine in browser JavaScript.

## Test gates

1. Decimal arithmetic: weights reconcile, zero/negative denominators reject, rounding does not hide residuals.
2. Disclosure coverage: full, partial, stale, empty and unresolved-ISIN fixtures.
3. Overlap: identical funds, disjoint funds, partial overlap, duplicate ISINs and asymmetric missing coverage.
4. AMC concentration: HHI/effective count invariants and unclassified AMC handling.
5. Targets: invalid bands, non-100% totals, effective-date history, concurrent edits and owner isolation.
6. Contribution preview: no transaction writes, no sell legs, residual cash reconciles, no hidden risk escalation.
7. Monthly comparison: market movement vs contribution/withdrawal vs classification/coverage change.
8. Snapshot immutability: later NAV/disclosure refresh does not alter a saved report.
9. API and UI: authentication, portfolio ownership, empty/error/loading states, mobile layout and accessibility.
10. Run SQLite and PostgreSQL suites; record exact commit SHA and CI result before review.

## Release boundary

Keep this work on `ui/portfolio-intelligence`. Do not merge to `main`, change `audit/production-foundation`, run production migrations, modify production data, or trigger a Render deployment as part of this specification. The open PR #135 currently targets `main` and is draft; reconcile its base and full diff separately before any merge decision.
