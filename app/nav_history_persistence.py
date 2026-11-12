"""Atomic persistence for one validated AMFI historical NAV window.

The caller must create/commit the checkpoint in "running" state before fetching.
This function commits observations, correction provenance, snapshot, and the
checkpoint's "complete" transition in one database transaction.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import select, tuple_

from app.db import (
    IngestionSnapshot,
    NavBackfillCheckpoint,
    NavObservation,
    NavObservationRevision,
    Scheme,
    SessionLocal,
)


def persist_historical_nav_window(
    checkpoint_id: int,
    records: list[Any],
    report: dict[str, Any],
    now: datetime,
    *,
    session_factory: Callable = SessionLocal,
) -> dict[str, int]:
    """Persist one validated window and mark it complete atomically."""
    if not records:
        raise ValueError("historical NAV window cannot be empty")
    required = ("payload_sha256", "records_valid", "unique_scheme_codes",
                "min_nav_date", "max_nav_date", "invalid_rows",
                "duplicate_rows_skipped", "quality_status")
    missing = [key for key in required if key not in report]
    if missing:
        raise ValueError(f"historical NAV report is missing fields: {', '.join(missing)}")

    with session_factory() as db:
        with db.begin():
            checkpoint = db.execute(
                select(NavBackfillCheckpoint)
                .where(NavBackfillCheckpoint.id == checkpoint_id)
                .with_for_update()
            ).scalar_one()
            if checkpoint.status != "running":
                raise ValueError("historical NAV checkpoint must be running")
            if any(record.nav_date < checkpoint.start_date or record.nav_date > checkpoint.end_date for record in records):
                raise ValueError("historical NAV record falls outside its checkpoint window")

            snapshot = IngestionSnapshot(
                source_url=checkpoint.source_url,
                retrieved_at=now,
                payload_sha256=report["payload_sha256"],
                records_valid=report["records_valid"],
                unique_scheme_codes=report["unique_scheme_codes"],
                min_nav_date=__import__("datetime").date.fromisoformat(report["min_nav_date"]),
                max_nav_date=__import__("datetime").date.fromisoformat(report["max_nav_date"]),
                invalid_rows=report["invalid_rows"],
                duplicate_rows_skipped=report["duplicate_rows_skipped"],
                quality_status=report["quality_status"],
                report_json=__import__("json").dumps(report, ensure_ascii=False),
            )
            db.add(snapshot)
            db.flush()

            codes = sorted({record.scheme_code for record in records})
            schemes = {
                row.scheme_code: row
                for offset in range(0, len(codes), 500)
                for row in db.execute(
                    select(Scheme).where(Scheme.scheme_code.in_(codes[offset:offset + 500]))
                ).scalars()
            }
            for record in records:
                scheme = schemes.get(record.scheme_code)
                if scheme is None:
                    scheme = Scheme(
                        scheme_code=record.scheme_code,
                        scheme_name=record.scheme_name,
                        isin_growth=record.isin_growth,
                        isin_dividend_reinvestment=record.isin_dividend_reinvestment,
                        first_seen_at=now,
                        last_seen_at=now,
                        plan_type=record.plan_type,
                        option_type=record.option_type,
                    )
                    db.add(scheme)
                    schemes[record.scheme_code] = scheme
                else:
                    scheme.scheme_name = record.scheme_name
                    scheme.isin_growth = record.isin_growth or scheme.isin_growth
                    scheme.isin_dividend_reinvestment = (
                        record.isin_dividend_reinvestment or scheme.isin_dividend_reinvestment
                    )
                    # The current AMFI archive schema carries plan and option
                    # metadata even though it does not carry category headings.
                    # Preserve existing values when an older archive variant omits them.
                    scheme.plan_type = record.plan_type or scheme.plan_type
                    scheme.option_type = record.option_type or scheme.option_type
                    scheme.last_seen_at = now
            db.flush()

            keys = [(record.scheme_code, record.nav_date) for record in records]
            existing: dict[tuple[int, Any], NavObservation] = {}
            for offset in range(0, len(keys), 400):
                batch = keys[offset:offset + 400]
                rows = db.execute(
                    select(NavObservation).where(
                        tuple_(NavObservation.scheme_code, NavObservation.nav_date).in_(batch)
                    )
                ).scalars()
                for row in rows:
                    existing[(row.scheme_code, row.nav_date)] = row

            inserted = updated = unchanged = 0
            for record in records:
                key = (record.scheme_code, record.nav_date)
                current = existing.get(key)
                if current is None:
                    db.add(NavObservation(
                        scheme_code=record.scheme_code,
                        nav_date=record.nav_date,
                        nav_value=record.nav,
                        source_snapshot_id=snapshot.id,
                    ))
                    inserted += 1
                elif Decimal(current.nav_value) != record.nav:
                    db.add(NavObservationRevision(
                        scheme_code=record.scheme_code,
                        nav_date=record.nav_date,
                        previous_nav_value=current.nav_value,
                        replacement_nav_value=record.nav,
                        previous_source_snapshot_id=current.source_snapshot_id,
                        replacement_source_snapshot_id=snapshot.id,
                        corrected_at=now,
                    ))
                    current.nav_value = record.nav
                    current.source_snapshot_id = snapshot.id
                    updated += 1
                else:
                    unchanged += 1

            checkpoint.status = "complete"
            checkpoint.payload_sha256 = report["payload_sha256"]
            checkpoint.records_valid = report["records_valid"]
            checkpoint.inserted_rows = inserted
            checkpoint.updated_rows = updated
            checkpoint.unchanged_rows = unchanged
            checkpoint.duplicate_rows = report["duplicate_rows_skipped"]
            checkpoint.invalid_rows = report["invalid_rows"]
            checkpoint.error_class = None
            checkpoint.completed_at = now
            checkpoint.updated_at = now

        return {
            "snapshot_id": snapshot.id,
            "inserted_rows": inserted,
            "updated_rows": updated,
            "unchanged_rows": unchanged,
        }
