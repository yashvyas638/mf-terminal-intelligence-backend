# NAV backfill checkpoint ledger

Migration `0012_nav_backfill_checkpoints` adds an internal ledger for each
bounded history request window and AMFI scheme type (1=open-ended, 2=close-ended,
3=interval; the mapping must still be confirmed against the official form).

The unique `window_key` is the idempotency identity supplied by the planner.
The checkpoint stores date bounds, attempts, source payload hash, row counters,
and a bounded error class (never raw response bodies, SQL parameters, or
credentials). Status is constrained to pending/running/complete/failed/paused.

A checkpoint can be marked complete only when `completed_at` is present.
Application code must update NAV rows and mark the checkpoint complete in the
same database transaction. A process crash before commit must leave neither
the NAV batch nor a completed checkpoint committed.

The table is internal: PostgreSQL RLS is enabled and all browser-role and
PUBLIC table privileges are revoked. No Data API read/write policy is created.

This migration does not run ingestion or create a production backfill job.
Historical source-contract verification, transaction-safe persistence, and
staging reconciliation remain separate gates.
