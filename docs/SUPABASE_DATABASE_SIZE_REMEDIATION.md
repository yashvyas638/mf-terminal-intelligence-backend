# Supabase database-size remediation

**Evidence date:** 18 November 2026  
**Project:** `mf-terminal-intelligence`

## Live measurements

Read-only SQL against the active project returned:

| Item | Measured size / count |
|---|---:|
| Application database | 519,689,907 bytes (about 496 MiB) |
| All cluster databases | 534,966,133 bytes (about 510 MiB) |
| `public.nav_observations` total | 380 MiB |
| NAV heap / indexes | 134 MiB / 246 MiB |
| NAV rows | 2,664,820 |
| `public.fund_research_snapshots` total | 94 MiB |
| Research snapshot rows | 34,852 |

The NAV table has four indexes. `ix_nav_code_date` and unique constraint index
`uq_nav_scheme_date` both use the same ordered key
`(scheme_code, nav_date)`. The duplicate non-unique index occupies
89,989,120 bytes (about 86 MiB). The unique constraint index is required for
data integrity/upsert conflict handling and is retained. The primary key and
source-snapshot foreign-key index are also retained.

The 500 MB Free-plan database-size quota is distinct from provisioned disk size.
Supabase evaluates fair-use database size using average daily usage over the
billing period, so a live reduction may not immediately clear an organization
restriction.

## Implemented repository change

Migration `0033_remove_duplicate_nav_index` drops only
`public.ix_nav_code_date`, if present. SQLAlchemy metadata no longer declares
that duplicate index. The unique constraint, primary key and all NAV rows are
preserved. No NAV rows, research snapshots, portfolio data or audit history
are deleted. Downgrade recreates the redundant index.

## Existing NAV sampling state

The live checkpoint ledger shows the hybrid history strategy is already in
place: completed daily windows cover the recent daily segment and short
five-year baseline buffer; completed month-end windows cover older history;
obsolete daily windows remain paused. This preserves recent daily risk
observations and month-end historical return anchors. Do not bulk-delete NAV
observations or change sampling boundaries without validating return,
volatility, drawdown, rolling-return and report consumers.

## Research snapshot footprint

The research cache contains 8,713 rows for each of four windows (30, 365, 1,095
and 1,825 days). Its total footprint is 94 MiB, including 23 MiB of indexes.
These rows are current cache inputs to screener ordering and research views.
Do not prune a window or change the snapshot payload format until all readers,
rebuild paths, freshness gates and ranking fallbacks are tested.

## Production execution boundary

This branch prepares the migration and regression test only. It does not run
the migration, modify production data, deploy Render or change Supabase
configuration. Apply only through the reviewed production migration path,
after the migration credential/startup blocker and backup/restore readiness are
resolved. Verify that:
- `ix_nav_code_date` is absent;
- `uq_nav_scheme_date` remains valid and unique;
- NAV row count and date coverage are unchanged;
- NAV history, research, risk and TWT report tests pass;
- database size is remeasured (usage metrics may update with delay).

## Further work

1. Measure again after removing the duplicate index.
2. Profile research snapshot JSON and index usage against actual API query plans.
3. Keep all four research windows unless a consumer audit proves one redundant.
4. Monitor NAV row growth and checkpoint sampling modes to prevent accidental
   full-history daily backfills.
5. Add a quota warning threshold and operator-facing size report before 90%
   of the Free-plan quota.
