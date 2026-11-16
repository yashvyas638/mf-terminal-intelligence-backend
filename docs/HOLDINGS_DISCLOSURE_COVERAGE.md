# Holdings disclosure coverage and security concentration

## Current data boundary

Holdings are imported as immutable, dated disclosure snapshots. Every import is
stored as `PENDING` and is excluded from analytics until an operator
checks the linked source document and verifies it. Only the latest `VERIFIED`
disclosure on or before the requested as-of date is selected for a scheme.

The source file hash, source URL, disclosure date, retrieval timestamp, row
count and total disclosed weight are retained. Re-importing the same scheme,
date and exact source hash is idempotent. A different source file for the same
scheme/date records which prior disclosure it supersedes.

## Parser safeguards

- Reject empty or oversized CSV files and more than 20,000 rows.
- Require security name and percent-to-net-assets columns. Accepts common AMC labels and
  SEBI Format 4C labels including `Name of the instrument`, `% to NAV`, and
  `Mkt value (Rs in lakhs)`; lakh-denominated market values are converted to INR.
- Reject duplicate/ambiguous normalized headers, extra row values, invalid
  ISINs, non-finite weights, unsupported numeric bounds and precision loss.
- A blank optional market value remains null; it is not coerced to zero.
- Repeated ISIN rows are aggregated only when asset-type/sector classifications
  do not conflict.
- Non-ISIN rows receive deterministic normalized-name IDs within the source
  disclosure; they are not treated as globally matched issuers.
- The parser reports total weight and variance from 100%. A non-100% total is
  surfaced as `REVIEW_REQUIRED` rather than silently normalized.

## Portfolio coverage

`GET /v1/portfolios/{portfolio_id}/lookthrough` reports:

- `COMPLETE` only when portfolio valuation is complete and every valued
  scheme has a verified disclosure within the requested age limit.
- `PARTIAL_MISSING_DISCLOSURES` when one or more valued schemes have no
  verified disclosure.
- `PARTIAL_STALE_DISCLOSURES` when disclosures exist but exceed the
  requested maximum age.
- `INCOMPLETE_PORTFOLIO_VALUATION` when NAV coverage prevents a complete
  portfolio denominator.

Fresh and stale disclosure market values are reported separately. Stale
verified disclosures remain visible for context but are explicitly identified;
they must not be presented as current holdings. Missing disclosure exposure is
not inferred.

## Security identity and concentration

Cross-fund aggregation is performed only for ISIN-identified securities.
Non-ISIN name-based rows remain disclosure-local to avoid false matches.

The response now includes a `security_concentration` object calculated on
positive exposure from observed verified disclosures only:

- top 1, top 5 and top 10 concentration;
- HHI points and effective security count;
- ISIN identity coverage;
- positive and negative disclosed exposure totals;
- observed positive exposure as a percentage of total portfolio value only
  when portfolio valuation is complete.

Negative exposures are shown separately and excluded from HHI. The denominator
for top-N and HHI is positive observed disclosed exposure, not total portfolio
value. Partial disclosure coverage can hide additional concentration, so these
figures are not a complete risk measure.

## Verification completed

- Route-level portfolio ownership isolation includes the look-through endpoint:
  a different authenticated user receives not-found rather than portfolio data.
- Portfolio integration tests exercise verified holdings, coverage, security
  concentration, identity basis and freshness split.
- Pure calculation tests cover partial valuation denominator behavior, empty
  disclosures, negative exposures and fresh/stale concentration splits.
- Parser regression tests include SEBI Format 4C headers and the rupees-in-lakhs
  scale conversion.

## Remaining release/data gates

1. Add and reconcile real official AMC/AMFI downloadable spreadsheet fixtures
   across equity, debt, hybrid, ETF and cash-heavy schemes. Current tests use
   deterministic synthetic fixtures; they do not claim live source validation.
2. Extend the ingestion pipeline to read the original XLS/XLSX files directly;
   the current endpoint accepts CSV text, so a spreadsheet must be converted
   to CSV before import.
3. Add an operator workflow for discovery/download, provenance capture,
   verification and scheduled refresh of AMC/AMFI source files.
4. Add security-level market-price history only from a licensed/reliable source
   with corporate-action adjustment and explicit coverage. Monthly holdings
   disclosures alone cannot produce live security volatility or VaR.
  
## Official reference

SEBI Master Circular for Mutual Funds dated 20 March 2026, Chapter 6, clause
6.1.1 requires monthly scheme portfolio disclosure with ISIN within 10 calendar
days of month-end; debt schemes have fortnightly disclosure including yield
within 5 calendar days. The prescribed portfolio format is Format 4C.
Official sources:
- AMFI portfolio disclosure portal: https://www.amfiindia.com/online-center/portfolio-disclosure
- SEBI Master Circular: https://www.sebi.gov.in/sebi_data/attachdocs/mar-2026/1774024028162.pdf
