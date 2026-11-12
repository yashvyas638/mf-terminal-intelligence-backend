# Benchmark TRI data contract and operating guide

## Why the benchmark layer exists

SEBI's mutual-fund benchmarking framework requires total-return variants of benchmarks for relevant schemes. TRI includes constituent dividends/interest in addition to capital movement; price-return index values alone are not a like-for-like benchmark for a growth mutual-fund NAV. SEBI also describes a two-tier structure for specified scheme categories: a broad category-representative first tier and an optional strategy/style second tier.

Primary references:
- SEBI circular on two-tier benchmark principles (27 Oct 2021): https://www.sebi.gov.in/legal/circulars/oct-2021/guiding-principles-for-bringing-uniformity-in-benchmarks-of-mutual-fund-schemes_53539.html
- SEBI Master Circular for Mutual Funds (20 Mar 2026): https://www.sebi.gov.in/sebi_data/attachdocs/mar-2026/1774024028162.pdf
- AMFI circulars and published first-tier benchmark lists: https://www.amfiindia.com/circulars
- NSE Indices official historical-data page, including Total Returns Index Values and CSV export: https://www.niftyindices.com/reports/historical-data
- NSE Indices data subscription information: https://niftyindices.com/offerings/data-subscription

## Data and licensing boundary

The official NSE Indices historical-data page exposes TRI and Net TRI values and a CSV export. NSE Indices separately describes ongoing/historical data products and data subscription. This implementation therefore accepts the official portal's CSV export through an operator-only import endpoint; it does not scrape an undocumented API or assume the public page grants unrestricted automated redistribution rights. Confirm the appropriate data-use permissions/subscription before commercial production use or broad redistribution.

## Import contract

Operator endpoint:

`POST /v1/benchmarks/import-csv`

The JSON body contains:
- `benchmark_code`: stable internal code, e.g. `NIFTY_50_TRI`
- `benchmark_name`: exact index name represented in the export
- `variant`: `TRI` or `NTR` only; price-return series are rejected
- `csv_text`: official CSV export text

Parser requirements:
- Date and matching total-return value column must be present.
- Rows are sorted by date; exact duplicate rows are deduplicated.
- Conflicting duplicate dates, multiple index names, non-positive values, malformed dates, empty files, files over 5 MB and exports over 20,000 rows are rejected.
- Values are stored as Decimal-backed numeric data with eight decimal places.
- The SHA-256 of the exact imported CSV is stored with every observation.
- Re-importing unchanged values is idempotent; changed values create a separate correction revision before the current value is replaced.

## Scheme-to-benchmark assignment

A benchmark series is not automatically assigned to a scheme based on its category or name. AMCs/trustees can change benchmarks and schemes can have tier-1 and tier-2 mappings.

Operator flow:
1. Read the current scheme factsheet/SID/official scheme disclosure.
2. Create a mapping using `POST /v1/benchmarks/assignments`, including tier, effective dates, source document URL and SHA-256.
3. The assignment is initially `PENDING`.
4. After a human review of the source document and effective dates, call `POST /v1/benchmarks/assignments/{id}/verify`.
5. Only `VERIFIED` assignments active on the requested as-of date are used in fund-vs-benchmark comparisons.

The app retains the evidence URL/hash and verification timestamp. Never map every fund in a category to a single benchmark without verifying the individual scheme disclosure and effective period.

## Comparison methodology

`GET /v1/analytics/research/{scheme_code}/benchmark?days=3650`

- Fund NAV and benchmark TRI are aligned on exact common dates only.
- No forward-fill or interpolation.
- Total return and CAGR are calculated over the common-date span.
- Daily beta, alpha, tracking error and information ratio require at least 30 adjacent common-date return pairs; pairs more than seven calendar days apart are excluded from those daily risk statistics.
- IDCW/payout schemes can distribute cash not reflected in NAV; the response warns that NAV-only fund returns are not distribution-adjusted investor total returns.
- Both benchmark tiers are shown when verified and active.
- Insufficient overlap returns explicit insufficient-data status rather than fabricated metrics.

## Current status

The schema, strict CSV parser, operator import endpoint, correction provenance, effective-dated mapping workflow, verification gate, exact-date comparison function and profile panel are implemented with fixture/API tests. The live official CSV export has not yet been imported or validated against a real scheme's latest official factsheet. No production benchmark series or scheme assignments are asserted as loaded.
