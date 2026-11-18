# Supabase database-size remediation

**Evidence date:** 18 November 2026  
**Project:** `mf-terminal-intelligence`  
**Scope:** Database-size quota and sustained NAV/research-data footprint

## Live measurements

Read-only SQL against the active Supabase project returned:

| Item | Measured size / count |
|---|---:|
| Current application database | 519,689,907 bytes (about 496 MiB) |
| All cluster databases | 534,966,133 bytes (about 510 MiB) |
| `public.nav_observations` total | 380 MiB |
| NAV heap | 134 MiB |
| NAV indexes | 246 MiB |
| NAV rows | 2,664,820 |
| `public.fund_research_snapshots` total | 94 MiB |
| Research snapshot rows | 34,852 |

The NAV table had four indexes. `ix_nav_code_date` and the unique constraint index
`uq_nav_scheme_date` both use the same ordered key: `(scheme_code, nav_date)`.
The duplicate non-unique index occupied 89,989,120 bytes (about 86 MiB).
The unique index is required for data integrity/upsert conflict handling and is
retained. The primary key and source-snapshot foreign-key index are also retained.

The 500 MB Free-plan database-size quota is distinct from provisioned disk size.
Supabase evaluates fair-use database size using average daily usage over the
billing period, so reducing the live database size may not immediately clear an
organization-level restriction.

## Implemented repository change

Migration `0033_remove_duplicate_nav_index` drops only
`public.ix_nav_code_date`, if present. The SQLAlchemy model no longer declares
that duplicate index. The unique `uq_nav_scheme_date` constraint and
`nav_observations_pkey` remain intact. No NAV rows, research snapshots,
portfolio data, or audit history are deleted.

The migration has a safe data-preserving effect; downgrade recreates the
redundant index for compatibility with the previous model. It is guarded for
fresh databases where the duplicate index was never created.

## Existing NAV sampling state

The checkpoint ledger shows the hybrid history strategy is already represented
in production data: completed daily windows cover the recent daily segment and
the short five-year baseline buffer; completed month-end windows cover older
history. Paused daily checkpoints remain paused. This preserves recent daily
risk observations and month-end historical return anchors. Do not bulk-delete
NAV observations or change sampling boundaries without validating all return,
volatility, drawdown, rolling-return, and report consumers.

## Research snapshot footprint

The research cache contains 8,713 rows for each of four windows (30, 365, 1,095,
and 1,825 days). Its total footprint is 94 MiB, including 23 MiB of indexes.
These rows are current cache inputs to screener ordering and research views.
Do not prune a window or change the snapshot payload format until all readers,
rebuild paths, freshness gates, and ranking fallbacks are tested. This is the
next optimisation target after the duplicate index is removed and measured.

## Production execution boundary

This branch prepares the migration and regression test only. It does not run
the migration, modify production data, deploy Render, or change Supabase
configuration. Apply it only through the reviewed production migration path,
after the migration credential/startup blocker and backup/restore readiness are
resolved. Verify afterwards that:
- `ix_nav_code_date` is absent;
- `uq_nav_scheme_date` remains valid and unique;
- row count and NAV date coverage are unchanged;
- NAV history, research, risk and TWT report tests pass;
- database size is remeasured (Supabase usage metrics may update with delay).

## Further work

1. Measure the database again after the duplicate index is removed.
2. Profile research snapshot JSON and index usage against actual API query plans.
3. Keep all four research windows unless a consumer audit proves one is redundant.
4. Monitor NAV row growth and checkpoint sampling modes to prevent accidental
   full-history daily backfills.
5. Add a quota warning threshold and an operator-facing size report before
   reaching 90% of the Free-plan quota.
