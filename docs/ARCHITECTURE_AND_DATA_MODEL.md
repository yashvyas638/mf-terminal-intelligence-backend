# Architecture and Canonical Data Model

## Logical architecture

1. **Source adapters:** AMFI, AMC factsheets, scheme documents, benchmark providers, macro/public data sources.
2. **Ingestion control plane:** scheduled/manual jobs, retries, rate limits, idempotency keys, source snapshots.
3. **Validation layer:** parser contracts, identity resolution, freshness/coverage checks, anomaly detection.
4. **Canonical data layer:** PostgreSQL/Supabase with versioned schema, constraints, indexes, audit and RLS.
5. **Analytics engine:** deterministic Python services for returns, risk, holdings, scenarios, tax and optimisation.
6. **API layer:** FastAPI versioned contracts, user-scoped authorization, caching and rate limits.
7. **Experience layer:** responsive web terminal, charts, tables, research drawers, import wizard and decision centre.
8. **AI layer:** retrieval and narration over approved structured metrics and source documents; no direct write access.
9. **Operations:** GitHub Actions CI/jobs, Render deployment, monitoring, backup, restore and incident runbooks.

## Data domains

- Identity: users, tenants, roles, sessions, consent.
- Scheme master: AMC, scheme code, ISINs, category, plan, option, benchmark, lifecycle.
- Source registry: source, document, URL, publication/effective date, fetched date, hash, parser version.
- NAV: ingestion snapshots, current observations, append-only corrections.
- Fund facts: AUM, expense ratio, exit load, manager, benchmark, factsheet metadata with as-of date.
- Holdings: portfolio snapshot, security master, holding rows, weights, sector, market cap, identifier match confidence.
- Benchmarks: benchmark master, dated observations, total-return/price-return series distinction.
- Portfolios: owner, portfolio, account/currency, transaction ledger, import batch, import rows, audit events.
- Analytics: metric definitions/version, computed results, input snapshot references, coverage and warnings.
- Macro: series master, observations, release calendar, revisions, event records.
- Decisions: research case, evidence references, assumptions, scenario, approval, action log and outcome.
- Tax/goals: tax rules with effective dates, lots, realised events, goals, assumptions and snapshots.
- AI: prompt/version, retrieval references, answer citations, feedback and safety/audit metadata.

## Identity and tenancy

- Every user-owned object must be scoped to an authenticated owner or tenant.
- Portfolio, import, transaction, goal, report and decision rows require ownership scope.
- A portfolio identifier is not authorization.
- Use RLS for database-enforced isolation plus application-layer checks.
- Background service roles must be narrowly scoped and never exposed to browsers.
- Public reference data (scheme/NAV/benchmark/macro) may be shared; personal portfolio data may not.
- Current single shared API key is a service integration mechanism, not a multi-user identity model.
- Do not enable external multi-user access until ownership migration, RLS, cross-tenant tests and security review pass.

## Canonical entity and relationship sketch

```text
User/Tenant
  ├── Portfolios
  │    ├── Import Batches ── Import Rows
  │    ├── Transactions ── Transaction Audit Events
  │    ├── Holdings/Valuations (derived)
  │    ├── Goals and Snapshots
  │    └── Decision Cases
  └── User Preferences / Watchlists / Alerts

AMC ── Schemes ── ISIN/Plan/Option/Category/Benchmark
                  ├── NAV Observations ── Ingestion Snapshot
                  │                      └── NAV Correction Revisions
                  ├── Fund Facts ── Source Documents
                  └── Holdings Snapshots ── Security Master

Benchmark ── Benchmark Observations
Macro Series ── Macro Observations ── Release/Event Calendar
Analytics Result ── Metric Definition + Input Snapshot References
AI Answer ── Retrieval Citations ── Source Documents / Analytics Results
```

## Important database design rules

- Use stable surrogate primary keys plus source identifiers with unique constraints.
- Store money/NAV/units as NUMERIC/Decimal with explicit precision.
- Store timestamps as timezone-aware UTC; store source-effective dates separately.
- Every time-varying fact has an effective/as-of date and source reference.
- Prefer append-only source snapshots and audit events.
- Use unique constraints for natural identity (e.g. scheme_code + nav_date) and indexes that match query patterns.
- Avoid storing derived analytics as truth without formula version and input snapshot IDs.
- Add indexes only from measured query plans; avoid speculative index bloat.
- Use foreign keys and check constraints for valid state transitions and non-negative values where appropriate.
- Use soft-void/audit semantics for financial corrections; do not hard-delete user ledger facts.
- Migration scripts must be backwards compatible during rolling deploys.

## Derived analytics provenance

Each computed result should include:
- metric_key and methodology_version
- subject IDs (scheme/portfolio/benchmark)
- start/end date and frequency
- computed_at UTC
- input snapshot IDs or input-data watermark
- parameters (risk-free rate, benchmark, rebalance frequency, tax regime)
- observation count and coverage ratio
- warnings, unsupported states and limitations
- result payload

Cache key must include subject, time range, methodology version, and data watermark. Invalidate when source data or methodology changes.

## Source hierarchy and conflict handling

- AMFI official NAV feed is the primary NAV source.
- AMC factsheets/SID/KIM and official AMC disclosures are primary fund-fact/holdings sources.
- Official benchmark/index provider is primary benchmark source.
- RBI/MOSPI/official government sources are primary domestic macro sources.
- Secondary sources may supplement but must be labelled and never silently override official data.
- If sources conflict, retain both observations, identify effective dates, show source priority and open a review issue; do not silently choose a convenient value.

## Data lifecycle

Fetch → preserve response metadata → parse → validate → normalise → stage → persist in transaction → reconcile → publish → calculate → cache → display.

Never publish staged/uncommitted data. Never discard raw evidence needed to explain a correction without a documented retention policy.
