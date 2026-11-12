# Holdings disclosure and overlap intelligence

## Official disclosure context

The SEBI Master Circular for Mutual Funds dated 20 March 2026, paragraph 6.1.1, states that AMCs/mutual funds disclose each scheme's portfolio with ISIN as of month-end on their own website and AMFI within 10 calendar days. Debt scheme disclosures are fortnightly within five calendar days. The disclosure is expected in a user-friendly downloadable spreadsheet format.

References:
- SEBI Master Circular for Mutual Funds (20 Mar 2026), Chapter 6, paragraph 6.1.1: https://www.sebi.gov.in/sebi_data/attachdocs/mar-2026/1774024028162.pdf
- AMFI Scheme-wise Disclosure portal: https://www.amfiindia.com/otherdata/scheme-wise-disclosure
- AMFI Portfolio Disclosure portal: https://www.amfiindia.com/investor-corner/online-center/portfoliodisclosure

## Data ingestion

Operator endpoint: `POST /v1/holdings/import-csv`.

The upload includes scheme code, as-of date, official source document URL, SHA-256 of the exact CSV text and CSV content. The server:
- Requires an HTTPS source URL and verifies the supplied SHA-256 against the exact uploaded CSV text.
- Requires a security name and % to Net Assets column.
- Validates any supplied ISIN using a strict 12-character format.
- Aggregates duplicate ISIN rows within one disclosure.
- Preserves rows without ISIN using a deterministic NONISIN identifier; these rows are never matched across funds.
- Stores the disclosure and normalized holdings as an immutable source snapshot.
- Re-importing the same scheme/date/source hash is idempotent.
- A new source hash for the same scheme/date creates a new disclosure that points to the prior disclosure it supersedes. The previous rows remain intact.

The importer accepts clean downloadable CSV exports. It does not assume every AMC uses the same workbook structure and does not scrape undocumented AMFI endpoints. If the source workbook has a different layout, it must be mapped and validated explicitly before import.

## Overlap methodology

Endpoint: `GET /v1/analytics/holdings-overlap?scheme_a={code}&scheme_b={code}`.

For each common valid ISIN:
- Read the positive % of net assets held by each scheme.
- The overlap contribution is the lower of the two weights.
- Total overlap percentage is the sum of those contributions.
- Also return shared exposure in each scheme separately, common ISIN count, top shared holdings and ISIN coverage.

Non-ISIN rows and negative exposures are excluded. No fuzzy security-name matching is performed. The two disclosure as-of dates and their age are shown independently; a disclosure older than 90 days is flagged stale.

## Limitations and safeguards

- Overlap is a dated holdings snapshot, not a prediction of correlation, drawdown or future performance.
- Cash, derivatives, collateral and other non-ISIN rows can affect reported portfolio weights and coverage.
- Holdings may differ by disclosure date; users must inspect both dates before relying on the comparison.
- The engine does not infer missing ISINs or silently match issuers by name.
- Production data ingestion and any redistribution must comply with source-provider and AMC terms.

## Current implementation boundary

The database schema, immutable disclosure importer, ISIN-aware parser, source hash validation, holdings retrieval endpoint, overlap endpoint, freshness/coverage warnings, Research Terminal overlap workspace and fixture/API tests are implemented. No real production holdings disclosures have yet been imported; overlap will correctly return unavailable until dated official files are loaded.
