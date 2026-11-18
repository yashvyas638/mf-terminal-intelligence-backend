# Historical AMFI NAV parser boundary

The historical parser is deliberately isolated in `app/nav_history.py`. It
expects the eight-column archive row layout:

1. Scheme Code
2. Scheme Name
3. ISIN Div Payout / ISIN Growth
4. ISIN Div Reinvestment
5. Net Asset Value
6. Repurchase Price
7. Sale Price
8. Date

It must not be used for `NAVAll.txt`, whose latest-feed parser lives in
`app/nav_ingest.py`.

The parser is a pure validation function: no HTTP requests, database writes,
scheme mutation, or historical backfill are performed. Its tests use a
representative archive-shaped fixture, not a captured response from the
official AMFI form. Therefore this change does **not** validate the historical
form's HTTP method, request parameters, type identifiers, or response-filter
semantics. Those remain a separate source-contract gate.

Before enabling a client or ingestion job, capture an actual response from the
official AMFI NAV History form and verify its header, columns, selected type,
date bounds, and scheme coverage against the requested form inputs.
