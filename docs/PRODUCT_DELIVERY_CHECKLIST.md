# Product Delivery Master Checklist

This is the release-control checklist for the nine product capabilities requested in the product build brief. A capability is not complete because a screen exists: it must pass its data, security, API, UX, automated-test and operational acceptance gates.

## Status definitions

- **Implemented / verified**: code and automated checks pass for the stated scope.
- **Implemented / live-unverified**: code exists, but the real provider, deployed environment or browser workflow has not been verified.
- **In progress**: partial foundation exists; acceptance criteria remain open.
- **Not started**: no production-grade implementation yet.
- Never promote a status without evidence. Record blockers and evidence links in the relevant PR.

## Master capability register

| Priority | Capability | Current status | Remaining acceptance gates |
|---|---|---|---|
| P0 | Live authentication and two-user isolation | Implemented / live-unverified | Verify real Supabase signup, email confirmation, sign-in, sign-out, refresh, password recovery and redirect URLs in a browser; pass two-user API isolation tests; verify production RLS and Supabase security advisors. |
| P0 | Historical NAV backfill and daily reconciliation | In progress | Capture and validate the official AMFI History form request/response; add historical response fixtures; bounded 90-day ingestion, durable checkpoints, idempotent persistence, correction provenance, retries/pause/resume; reconcile expected windows, source rows, stored rows and per-scheme coverage; verify scheduled daily runs. |
| P1 | Benchmark TRI and rolling-return comparisons | In progress — ingestion/mapping/comparison foundation built | Added TRI/NTR-only official Nifty CSV parser, source-hashed observation storage, correction revisions, effective-dated tier-1/tier-2 scheme mappings, PENDING→VERIFIED review workflow, exact-common-date fund-vs-TRI comparison API, alpha/beta/tracking error/information ratio with minimum observations, and profile comparison panel. Tests cover CSV validation, corrections, mapping review, date alignment and gaps. Remaining: verify NSE Indices data-use permissions, import a real official CSV, map real schemes from current official factsheets, and validate against independent calculations. |
| P1 | Watchlists and advanced fund screener | In progress — watchlist API/UI implemented | Per-user watchlist table, authenticated CRUD endpoints, duplicate handling, 500-item cap, RLS owner policies and UI save/remove/refresh/empty states are implemented. The global screener ranks the full matching precomputed snapshot universe before pagination, with metric selection, stable tie-breaking, classification filters, minimum-observation filters and freshness/as-of disclosure. Tests explicitly prove ranking occurs before pagination. Remaining: live browser E2E, production migration verification, production snapshot refresh/coverage validation and richer verified metadata. |
| P1 | Fund holdings and overlap intelligence | In progress — disclosure import and overlap engine built | Added immutable dated holdings snapshots, source URL/hash validation, strict ISIN parser, duplicate-ISIN aggregation, PENDING→VERIFIED operator review, holdings retrieval API, exact ISIN overlap with positive weights, coverage/freshness warnings, and Research Terminal overlap workspace. Tests cover parser, idempotent imports, corrections, verification gate and overlap math. Remaining: import and verify real monthly AMFI/AMC disclosures, test real workbook formats across AMCs and validate coverage. |
| P2 | Portfolio risk and stress testing | In progress — historical risk and explicit stress sensitivity built | Owner-scoped portfolio risk endpoint/UI calculates exact-common-date NAV portfolio returns, annualised volatility, downside deviation, Sharpe, drawdown, empirical 95% VaR/CVaR and worst 1D/5D/21D windows. User-defined per-holding shocks produce a clearly labelled sensitivity (not forecast). Added verified-disclosure look-through that aggregates underlying securities by ISIN, sector and source date, with stale/missing coverage surfaced and portfolio weights withheld for incomplete valuation. Tests cover common dates, gaps, risk tails, stress arithmetic, verified holdings aggregation and owner isolation. Remaining: live data validation, correlation matrix, security-level factor exposures and richer named macro scenarios. |
| P2 | Tax, capital gains and goal planning | In progress — FIFO lots and private goal scenarios built | Owner-scoped FIFO lot accounting matches redemptions to buys, includes recorded charges, reports realized/unrealized gains and holding periods; tax rates are intentionally not applied pending verified scheme classification and effective-dated Indian rules. Private per-user goals support target amount/date, inflation and low/base/high user-entered return scenarios, projected values and required monthly contributions. Goals can link to one of the owner's portfolios; projections use only complete, fresh market value and reject cross-owner, stale or incomplete linked data. Tests cover FIFO, oversells, projection assumptions, linked valuation and two-user isolation. Remaining: verified Indian tax-rule engine, exit-load treatment and qualified tax review. |
| P3 | AI-powered investment research | In progress — evidence pack foundation built | Added a machine-readable evidence pack API and profile panel with source IDs/URLs/hashes, AMFI NAV facts, methodology-labelled derived metrics, only VERIFIED benchmark/holdings sources, explicit data gaps and downstream AI guardrails. No LLM generation or AI recommendations are claimed yet. Remaining: secure model-provider integration/key management, retrieval/prompt-injection controls, claim-level citation enforcement, evaluation set, privacy isolation and investment-recommendation guardrails. |
| P3 | Professional reports and portfolio recommendations | In progress — immutable portfolio snapshots and PDF export built | Added owner-scoped report snapshots with content SHA-256 and retrieval-time integrity verification, NAV and verified holdings disclosure source provenance, valuation, historical risk, verified underlying security/sector look-through, FIFO pre-tax lots, methodology/limitations, report history API, dashboard report-history panel and server-generated PDF export. Tests verify snapshot persistence, integrity status and PDF signature. Recommendations are not generated; remaining: broader benchmark/holdings evidence, goal-aware suitability guardrails, report design validation, export/browser E2E and qualified review. |

## Global release gates

1. **Security**: authenticated user identity is verified server-side; every private query/write is owner-scoped; cross-user tests cover list, read, create, import, void, valuation and analytics routes; database RLS and least-privilege grants are checked.
2. **Data integrity**: no invented NAVs, benchmark values, holdings, fees, returns or tax outcomes; all imported records carry source and effective-date provenance; corrections are auditable.
3. **Financial methodology**: calculations use decimal-safe inputs where appropriate, documented cash-flow conventions, date alignment and explicit missing-data behavior.
4. **UX**: every feature has loading, empty, validation, error and success states; responsive layout; keyboard-accessible controls; no dead buttons or misleading labels.
5. **Quality**: unit, API, migration, SQLite and PostgreSQL CI; regression tests; relevant end-to-end browser verification before release.
6. **Operations**: migrations are reviewed and repeatable; scheduled jobs are observable; failures alert; backups and restore are tested; staging verification precedes production ingestion.
7. **Release**: PR review and CI success are necessary but not sufficient. Live provider and browser checks must be recorded separately. Do not deploy or merge a feature whose required gates remain open.

## Build order and dependencies

- Close P0 authentication and isolation before adding more user-owned features.
- Complete the historical NAV source adapter and reconciliation foundation before relying on long-horizon return/risk analytics.
- Benchmark TRI and holdings disclosure schemas, import parsers, source provenance, human verification gates and comparison/overlap engines are implemented. Real official source files and licensing/production validation remain outstanding.
- Watchlists can proceed on the authenticated user model once P0 isolation tests pass.
- AI research and professional reports must consume validated upstream data and expose uncertainty rather than conceal it. Portfolio historical risk, user-defined stress sensitivity, FIFO capital-gains lots and private goal scenarios now exist, but their live data/financial-rule acceptance gates remain open.

## Current evidence boundary (2026-11-12)

- The current feature branch has dashboard and research auth UX changes, server-side Supabase user verification, owner-scoped portfolio routes and RLS migration work. Private goal projections can now link to an owner-verified portfolio and use only fresh, complete market value.
- Latest CI run 43178353540 passed SQLite and PostgreSQL jobs at commit 2c3ae64d17de7bc1e963578e960a610fcffd3cf0. The two-user bearer-auth middleware/API isolation test passed SQLite and PostgreSQL CI at commit 74052cabbb36ee50e4725e303e03c845a7451417. The AMFI history adapter is a later addition and its latest CI run must pass before it is treated as verified.
- Live Supabase signup/login/email delivery and deployed browser E2E are not yet verified. Latest live-provider browser flows, report downloads and user-facing UI remain release-gated. The connected project audit found owner-scoped RLS policies on portfolio tables; the four RLS-enabled/no-policy INFO findings (migration metadata, ingestion snapshots, NAV corrections and backfill checkpoints) have no grants to anon/authenticated/PUBLIC, so they remain closed to client roles.
- Latest NAV ingestion and parser fixtures exist. Historical date-window planning, checkpoint schema, atomic persistence and an isolated bounded HTTP adapter now exist. Adapter HTTP tests use mocks; the official AMFI historical request contract is still not live-validated and production backfill is not enabled.
- Fund Explorer has classification filters and pagination. Per-user watchlists and global metric-ranked screener APIs are implemented; ranking is across all matching stored snapshots before pagination. Daily research snapshot refresh is wired after NAV ingestion, but a production refresh run and sufficient history are still unverified.


## TWT mutual-fund allocation report — implementation audit (2026-11-18)

The requested `docs/PROJECT_COMPLETION_MASTER.md` is not present on this branch. This delivery checklist is the available product-level master tracker and is updated here rather than creating a second competing tracker.

### Verified existing foundations

- **Scheme allocation:** the Portfolio Intelligence page calculates scheme weights from current market value when valuation is complete. Incomplete valuation suppresses the weight display.
- **Underlying holdings / sector look-through:** the owner-scoped `GET /v1/portfolios/{id}/lookthrough` endpoint uses only VERIFIED disclosures, reports missing/stale disclosure coverage, aggregates ISIN securities and sectors, and returns a security-concentration object. It is not a market-cap report.
- **Overlap foundation:** the allocation-intelligence specification documents a pairwise common-ISIN overlap engine. The current portfolio UI does not expose a portfolio-wide overlap matrix or weighted duplication view.
- **Snapshots and PDF:** owner-scoped immutable portfolio report snapshots, SHA-256 integrity verification, report history and server-side PDF export exist. These are general portfolio reports, not yet the complete TWT allocation report.
- **Responsive baseline:** the Portfolio Intelligence stylesheet has breakpoints at 1100px, 760px and 480px. Static DOM audit found 48 unique IDs, no duplicate IDs and no missing IDs referenced by its JavaScript. This is not a substitute for browser/device E2E.

### Additional TWT allocation delivery (2026-11-18)

- `ac51891cd517f0c5fb79abcd39b00e5e07322489` — extended the owner-scoped portfolio look-through response with market-value-weighted AMC concentration, category, category-group and asset-class allocations. Includes explicit Unclassified buckets, coverage labels, scheme counts, observed-weight concentration, HHI and effective AMC count. Percentages are withheld unless total portfolio valuation is complete.
- `ce1b8ad9ac8ad8a2ba2fce160230c873ceaadb84` and `6ff9e9853cf560a3b4f18809f9b88f41c41edda5` — added AMC, category and asset-class panels to the Portfolio Intelligence look-through workspace.
- `820dd45a6157b17f82c76f8bafe09b82c4393ffa` — extended the existing authenticated portfolio integration fixture to assert AMC, category, category-group, asset-class and concentration outputs.
- `01181a52342fbb070522002104b1a5a09dbdc0fc` — added frontend contract checks for the new panels and API fields.

**Methodology boundary:** AMC/category/asset-class rollups use current scheme market value and existing scheme metadata. Missing metadata is grouped as Unclassified, not guessed. These rollups do not solve the separate underlying-security market-cap classification problem. No verified, effective-dated large/mid/small-cap security classification source is currently present.

### Monthly comparison and report export additions (2026-11-18)

- `b3fe42bb1d7de708a9a6368060f5ca4a21e55673` — added an owner-scoped `GET /v1/portfolios/{id}/monthly-review` endpoint. It chooses the latest hash-valid immutable report snapshot per calendar month, compares the latest two months, returns portfolio value change and AMC/category/asset-class weight changes, and flags new/missing classifications. It explicitly does not claim to separate contributions, withdrawals and market movement.
- `0f257968751fcfa74e7598f7815c1c7c65d412f5` — added an integration fixture for a two-month snapshot comparison, integrity hash, value delta and AMC movement.
- `6f8a2f8ec25c3f8d0a326def58f31997ffda597d`, `3d5bfba10efa019f2acc30a7ca8af0cf6c41d75d`, `9ba22c645c6e5b822dc5dd261253631fd1a52c51` — added monthly review UI, API loading and refresh after a new report is generated.
- `df057843e490600779e32d8bcb80f6e5c4ab1ab5` — added a frontend contract test for monthly comparison and the insufficient-history state.
- `70154613b4c42e351368213ce0ae45b5c02bb9a3` — added AMC concentration, scheme category and asset-class allocation tables to PDF output.
- `f0402b52ac0ce9648989115763919b48367f9cd0` — added a PDF regression fixture containing AMC/category/asset-class data.
- `d8a5659dae36b2a3e19f13aed17311ac2753111c` — included monthly-review in the cross-user portfolio isolation route contract.

**Monthly comparison limits:** A comparison requires valid report snapshots from two distinct calendar months. The selected snapshots are latest generated report per month, not guaranteed month-end valuations. Flow-versus-market attribution is not available; value movement is net movement only. The API withholds value change unless both valuations are complete.

### Market-cap evidence gate (2026-11-18)

- `a86a41dab537497fc71895393d11483e3dcfe24c` — added an explicit `market_cap_allocation.status = NOT_CONFIGURED` contract to portfolio look-through. No market-cap percentages or zero values are fabricated without verified effective-dated security classifications.
- `b8a41471c3b8e2c29d3bb7af6872aa8bee254437`, `5e131aefa8749bcf2f4d8b27e6009db71a477c1a`, `7699b37758d5599515fe84680d3e7d21b033c6f3` — surfaced the market-cap limitation in UI and PDF.
- `f7ba5137cc028039a91275f35e8e35ba263b28a6`, `0e24b7b6da5bb1c322786c2c846eb8dac78f13d9` — added API/UI contract assertions for this withheld state.

**Remaining critical data dependency:** To deliver actual large/mid/small-cap exposure, add an operator-reviewed, source-hashed, effective-dated ISIN classification feed and backfill classifications for holdings. Until that feed is available and verified, market-cap allocation is correctly withheld. Portfolio-wide overlap matrix and flow-versus-market monthly attribution are also still open; current pairwise overlap is scheme-level only.

**Branch state after these commits:** `audit/production-foundation` is 655 commits ahead and 57 behind `main` at the last comparison. This divergence remains a release blocker; do not merge wholesale.

### Fixes committed on `audit/production-foundation`

- `2e73dd962afdc07f8bd63d126c3c522bd86402ac` — corrected look-through concentration percentages. API values are already percentage points; the UI had divided ISIN coverage and top-1/5/10 weights by 100, displaying values 100 times too small. Also corrected the diagnosis panel to read `security_concentration`, the actual API response key.
- `68312f997ec181b6b336d4ec53bcf1eeced7305b` — added regression assertions for those rendering contracts.
- `44074b9b21c6cb0376f2cd83edf5c2709b338bc2` — corrected PDF holding rows to derive weights from the complete portfolio value and read the actual `nav_freshness` field. Weights remain withheld for incomplete valuation.
- `f5c18188ab13b0a268386e36bd26c3d5266075f7` — added PDF regression tests for complete/incomplete valuation, invalid inputs and PDF signature.
- `c0c1e0296391112f25b4ca51f6aea8c43c56a291` — guarded asynchronous risk results so a response from a previously selected portfolio or signed-in session cannot overwrite the current workspace; also resets the risk error state before retrying.
- `74a21b61f94c3e6810f32b8d126185e80f6afa17` — added a regression contract for stale risk-request suppression and error-state reset.

### Remaining TWT acceptance gates

| Capability | Status | Evidence still required |
|---|---|---|
| Fund / segment / category allocation | Partial | Add category and segment rollups with both total-portfolio weight and within-segment contribution; reconcile to portfolio value and verified classification coverage. |
| Underlying market-cap look-through | Not implemented | No effective-dated, source-hashed security market-cap classification pipeline or large/mid/small/unclassified portfolio aggregation was found in the candidate API. Do not infer market cap from scheme category. |
| Fund overlap | Partial foundation | Add owner-scoped portfolio overlap matrix, common-security detail, matched-ISIN coverage, disclosure dates and a tested non-double-counting portfolio duplication metric. |
| AMC concentration | Not implemented | Add verified AMC mapping and market-value-weighted AMC exposure, top-1/3/5, HHI and effective AMC count. |
| Month-on-month comparison | Not implemented | Add comparable monthly snapshots and flow/market-movement/source-refresh attribution; the current monthly review screen is a framework, not a comparison engine. |
| TWT report rendering / PDF | Partial | Build the dedicated report from the above metrics, align on-screen and PDF values, include provenance/coverage/limitations and test real multi-page exports. Current PDF is a general portfolio report. |
| Responsive / browser verification | Partial | Static checks only. Run authenticated browser E2E at desktop, tablet and mobile widths, including empty, partial, stale and failed API states. |

### Validation and release boundary

- The latest commits above are on `audit/production-foundation`; no changes were made to `main`, production data, secrets or Render configuration.
- The branch is substantially divergent from `main` (comparison observed 631 commits ahead and 57 behind). Do not merge the entire branch without a deliberate reconciliation plan.
- The connected GitHub status endpoint returned no status checks for the latest fix commit, and the available workflow-run lookup returned no PR-triggered runs. The test files have been committed, but execution of the new tests and full SQLite/PostgreSQL CI is **not yet verified**.
- Live Supabase/Auth, real disclosure coverage, actual browser downloads and production PDF rendering remain unverified. No production deployment is authorised by this audit.


### Portfolio-wide fund overlap matrix (2026-11-18)

- `02caeb75ff6668506301294d059471c25e630480` — added authenticated, owner-scoped `GET /v1/portfolios/{id}/holdings-overlap`. It selects the latest VERIFIED disclosure per scheme, reports disclosure dates, SHA-256 source fingerprints, disclosure age and positive-weight ISIN coverage, and calculates pairwise common-ISIN overlap.
- `82001c9d2ec1a9f4f4df7ece928debfa25be0c52` — added API integration assertions for the new endpoint and added it to the cross-user portfolio isolation route contract.
- `fab33ffea719b91c7459ee6864343b838a20be2d` and `4d0f3f2715b8672fe22ce7933655ef2419f34698` — added the portfolio overlap panel to Portfolio Intelligence, including disclosure freshness, ISIN coverage, pairwise overlap and shared security counts.
- Methodology guardrail: overlap contribution per shared ISIN is the lower of the two positive scheme weights. Non-ISIN and negative-weight rows are excluded. Pairwise percentages are explicitly non-additive; no portfolio-wide duplication percentage is fabricated from pair sums.
- Remaining: execute API and browser tests in CI; add a fixture with at least two portfolio funds and shared ISINs to assert exact matrix arithmetic; include overlap in immutable report/PDF output; inspect query performance for larger portfolios.

- `111a59f6acedef7da5dbedd788db715d1ab5d6d5` — immutable report snapshots now capture the same portfolio-wide overlap result alongside the valuation and look-through evidence.
- `d0f8546084c1096677960e5d4f7985151288e820` — PDF report includes the pairwise overlap table and its non-additivity warning.
- `f64185b148379524765aa8ba072fb762461972bf` and `582f34d3ddad7a8a340e7448e3b0b36a03b24649` — added report snapshot and PDF regression assertions/fixture.
- `ba504136d58e88835dc0b1d676558fc1f886b3e5` — added frontend contract coverage for the overlap panel.

### Validation state after overlap integration (2026-11-18)

- Latest audit branch head at this checkpoint: `3811a770d270289fc81cb38f4f1fe12f900ebc2a`.
- Static DOM check: 56 HTML IDs, no duplicate IDs, and no missing IDs referenced by the Portfolio Intelligence JavaScript.
- GitHub Actions CI for the latest branch head was observed in `queued` state; no successful test result is claimed until the run completes.
- The existing PR #1 remains open and GitHub reports `mergeable=false`. Branch comparison against `main`: `diverged`, 673 commits ahead and 57 behind. Do not merge blindly; reconcile the base divergence and review the full diff first.
- No production deployment, production data change, or database migration was performed as part of this report feature work.

- `981d4b4a0c96b69747743074fdcb78a3d0b95627` — hardened overlap coverage status: portfolios with fewer than two valued funds now return `INSUFFICIENT_FUNDS`; missing verified disclosure coverage remains explicit; duplicate ISIN rows are normalized and their positive weights are aggregated rather than silently overwritten.
- `42d1220396a7a94288beef6fb0e5d317f2b2b8d9` and `82b11fad166d0c22dc4d317d223a66407852bc75` — added an exact two-fund portfolio fixture covering shared ISIN overlap arithmetic, duplicate case-normalized ISIN aggregation, ISIN coverage, and cross-user isolation; corrected the single-fund expectation to `INSUFFICIENT_FUNDS`.

- `393f51661122a210608623892957721d9c2b8fb4` — added the overlap methodology to the immutable report's machine-readable methodology metadata.
- `e670a7000eee93751182f0d318f813489651196d` — escaped backend status fields in overlap UI table rendering.
