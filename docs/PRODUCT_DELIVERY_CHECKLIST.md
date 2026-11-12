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
| P1 | Benchmark TRI and rolling-return comparisons | Not started | Source benchmark TRI from a licensed/official verifiable feed; store provenance and effective dates; align fund and benchmark dates; implement point-to-point, calendar-year and rolling returns with explicit methodology; tests for gaps, holidays, inception and insufficient history. |
| P1 | Watchlists and advanced fund screener | In progress — watchlist API/UI implemented | Per-user watchlist table, authenticated CRUD endpoints, duplicate handling, 500-item cap, RLS owner policies and UI save/remove/refresh/empty states are implemented. CI passed API isolation and migration tests at 0cae4a5 and JavaScript checks at 1b9843a; latest query optimization is awaiting CI. Remaining: live browser E2E, production migration verification, and a globally ranked screener backed by precomputed metrics (current page sorting is not global). |
| P1 | Fund holdings and overlap intelligence | Not started | Acquire dated official portfolio disclosures; normalize security identifiers and weights; report disclosure date/coverage; calculate pairwise overlap with explainable denominator and missing-data warnings; tests for duplicate identifiers and stale disclosures. |
| P2 | Portfolio risk and stress testing | Not started | Implement risk measures from adequate return histories; portfolio aggregation and correlation assumptions; named historical/hypothetical scenarios; disclose limitations and avoid false precision; validate with deterministic fixtures. |
| P2 | Tax, capital gains and goal planning | Not started | Lot-level acquisition/redemption records; Indian equity/debt tax rules with effective dates and source citations; exit-load handling; goal timelines, inflation and contribution scenarios; clear estimates vs tax advice; boundary tests for rule changes. |
| P3 | AI-powered investment research | Not started | Retrieval limited to trusted, dated sources; claim-level citations; separate facts, calculations and model interpretation; no fabricated fund facts or guaranteed returns; user-data isolation, prompt-injection controls and evaluation set. |
| P3 | Professional reports and portfolio recommendations | Not started | Reproducible report snapshots; source/methodology appendix; risk and suitability guardrails; recommendations linked to user goals and verified inputs; PDF/export tests and audit trail. |

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
- Benchmark TRI and holdings disclosures are independent source integrations; each needs its own verified feed and data-quality contract.
- Watchlists can proceed on the authenticated user model once P0 isolation tests pass.
- Risk, tax, goals, AI research and reports must consume validated upstream data and expose uncertainty rather than conceal it.

## Current evidence boundary (2026-11-12)

- The current feature branch has dashboard and research auth UX changes, server-side Supabase user verification, owner-scoped portfolio routes and RLS migration work.
- CI run 43168199878 passed SQLite and PostgreSQL jobs at commit 61b134b86a123dcc3e97fdd64c67fdcef0669b00. The two-user bearer-auth middleware/API isolation test passed SQLite and PostgreSQL CI at commit 74052cabbb36ee50e4725e303e03c845a7451417. The AMFI history adapter is a later addition and its latest CI run must pass before it is treated as verified.
- Live Supabase signup/login/email delivery and deployed browser E2E are not yet verified. The connected project audit found owner-scoped RLS policies on portfolio tables; the four RLS-enabled/no-policy INFO findings (migration metadata, ingestion snapshots, NAV corrections and backfill checkpoints) have no grants to anon/authenticated/PUBLIC, so they remain closed to client roles.
- Latest NAV ingestion and parser fixtures exist. Historical date-window planning, checkpoint schema, atomic persistence and an isolated bounded HTTP adapter now exist. Adapter HTTP tests use mocks; the official AMFI historical request contract is still not live-validated and production backfill is not enabled.
- Fund Explorer has classification filters and pagination. Per-user watchlist API and UI have been implemented with isolated storage and a database migration; live browser verification remains. The metric-ranked global screener is still incomplete.
