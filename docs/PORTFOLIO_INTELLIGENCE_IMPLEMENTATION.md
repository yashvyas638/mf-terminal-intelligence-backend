# Portfolio Intelligence implementation notes

This document describes the candidate implementation on `ui/portfolio-intelligence`.
It is not a production-release approval.

## Workspace

Open `/intelligence` after authentication. The workspace loads the signed-in user's own portfolios and provides:

- Overview: transaction-ledger valuation, NAV freshness and holdings.
- Allocation: scheme, category, sub-category, asset-class and AMC weights.
- Look-through: verified disclosure coverage, sector and security exposure.
- Risk Lab: historical risk estimates using the existing risk endpoint.
- Monthly Review: immutable report snapshots, downloadable PDF and month-on-month comparison.

All portfolio endpoints require the authenticated owner. The UI does not call operator-only ingestion routes.

## Allocation and concentration

- Scheme weights use current valued market values.
- Category, sub-category and asset-class labels come from the stored scheme master. They are not inferred from scheme names.
- AMC concentration aggregates scheme market value by stored AMC metadata. It exposes top-1/3/5, HHI and effective AMC count.
- These values are scheme-level allocation. They are not a substitute for underlying market-cap or issuer concentration.

API: `GET /v1/portfolios/{portfolio_id}/allocation`

## Verified look-through and overlap

- Only the latest eligible `VERIFIED` disclosure for each scheme is included.
- ISIN is the cross-fund identity key. Non-ISIN labels are not cross-matched.
- Pairwise overlap is the sum of the lower fund weight for each common positive ISIN.
- Portfolio-wide duplicated exposure is calculated per security as total included fund exposure less the largest single-fund contribution. Pairwise percentages are never summed to estimate portfolio duplication.
- Stale or missing disclosures are explicitly listed. Overlap is not return correlation.
- Pairwise computation is withheld above 200 active funds to bound quadratic work.

API: `GET /v1/portfolios/{portfolio_id}/overlap-matrix`

## Market-cap classification source workflow

The engine does not infer company market cap from a name, ticker or fund category.

The operator import accepts a CSV with these required columns:

```csv
ISIN,Market Cap Bucket,Effective From,Effective To,Source As Of Date
INE002A01018,Large,2026-01-01,,2026-10-31
INE009A01021,Mid Cap,2026-01-01,2026-12-31,2026-10-31
```

- Bucket values: `LARGE_CAP`, `MID_CAP`, `SMALL_CAP`, `OTHER` (the parser also accepts Large, Mid and Small aliases).
- Dates must be `YYYY-MM-DD`.
- Every imported batch is stored as `PENDING`, with a SHA-256 of the exact imported CSV text and the supplied HTTPS source-document URL.
- Only an operator can verify or reject a batch. Verification is blocked when a different verified source already assigns the same ISIN from the same effective date.
- The calculation uses the latest effective verified mapping as of the look-through date. Stale, missing, non-ISIN and conflicting mappings are not silently normalised away.
- The CSV digest identifies the imported CSV artifact. Keep the original official source document and its review evidence with the release record.

Operator APIs (require the operator API key):

- `POST /v1/market-cap/classifications/import`
- `POST /v1/market-cap/classifications/{source_sha256}/verify`
- `POST /v1/market-cap/classifications/{source_sha256}/reject`

Owner-scoped analysis API:

- `GET /v1/portfolios/{portfolio_id}/market-cap-allocation`

Market-cap output distinguishes look-through coverage from classification coverage. Unclassified exposure remains visible and is not redistributed to Large/Mid/Small.

## Target policy and contribution preview

Target policies are owner-scoped and effective-dated. Each same-day revision gets a monotonically increasing version; previous versions remain stored.

Supported dimensions in this release: asset class, category, sub-category, AMC and scheme. Market-cap and sector targets are deliberately disabled until complete verified classification coverage and matching actual-value aggregation are available.

- `GET /v1/portfolios/{portfolio_id}/targets`
- `PUT /v1/portfolios/{portfolio_id}/targets`
- `GET /v1/portfolios/{portfolio_id}/allocation-drift?dimension=ASSET_CLASS`
- `POST /v1/portfolios/{portfolio_id}/contribution-plan/preview`

Target sets must cover the exact current valued keys in the chosen dimension, have unique keys, satisfy min ≤ target ≤ max, and preferred targets must sum to 100%. Drift requires complete valuation and fresh NAVs.

Contribution preview allocates new cash to positive target gaps only, capped at the remaining target deficits. It does not execute trades, propose sells, or yet apply separate AMC, sector, liquidity or risk-budget caps.

## Monthly snapshots

Each new immutable report snapshot now stores:

- Valuation, holdings and historical risk.
- Verified holdings look-through and sector exposure.
- Scheme/category/asset-class/AMC allocation.
- Pairwise fund overlap and portfolio-wide duplicated exposure.
- Verified market-cap distribution and unclassified exposure.
- Source URLs, source hashes, as-of dates and limitations.

The PDF renders the allocation, AMC, overlap and market-cap sections. The monthly comparison endpoint compares the two latest saved snapshots:

- `GET /v1/portfolios/{portfolio_id}/monthly-comparison`

It is a two-snapshot comparison, not a daily time series. Disclosure and classification refreshes can change look-through values independently of trades and market movement.

## Candidate database migrations

- `0030_portfolio_targets`: owner-scoped effective-dated target policies with immutable same-day versions.
- `0031_security_mcap`: source-hashed, effective-dated market-cap classifications.

These migrations are only in the candidate branch. Do not apply them to production until the privileged migration connection, backup and restore evidence, runtime-role permissions and release approval are all verified.

## Release gates still open

- CI currently reports five unrelated baseline failures in screener ranking, monthly leaderboard bootstrap, stale-NAV risk expectation and two NAV refresh tests. The new allocation/market-cap unit tests, target constraints, frontend syntax checks, lint and UI contract checks pass in the latest observed SQLite run.
- PostgreSQL run completion must be confirmed for the final branch head.
- Production Render is connected to a different branch with auto-deploy enabled. Keep working on this candidate branch; do not merge or deploy until the migration and backup gates are closed.
- No live market-cap classifications have been imported or verified as part of this code change. Until an official source batch is reviewed and verified, the market-cap view will correctly show unclassified exposure rather than fabricate a split.
