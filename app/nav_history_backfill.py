"""Checkpointed orchestration for bounded AMFI historical NAV backfills.

This service is opt-in and never schedules itself. The candidate AMFI HTTP
contract must be verified against the official History form before execution
is enabled in a production environment.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import calendar
import hashlib
from typing import Any, Callable

from sqlalchemy import func, select

from app.db import NavBackfillCheckpoint, SessionLocal
from app.nav_backfill import HistoryWindow, plan_history_windows
from app.nav_history_persistence import persist_historical_nav_window
from app.nav_history_source import build_amfi_history_url, fetch_amfi_history_window


def _checkpoint_key(window: HistoryWindow, scheme_type: int) -> str:
    raw = f"amfi-nav-history|type={scheme_type}|{window.start_date.isoformat()}|{window.end_date.isoformat()}"
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def create_history_backfill_plan(
    start_date: date,
    end_date: date,
    scheme_types: tuple[int, ...] = (1, 2, 3),
    *,
    max_window_days: int = 7,
    session_factory: Callable = SessionLocal,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create idempotent pending checkpoints without making network requests."""
    if not scheme_types or any(
        not isinstance(value, int) or isinstance(value, bool) or value not in {1, 2, 3}
        for value in scheme_types
    ):
        raise ValueError("scheme_types must contain one or more values from 1, 2, 3")
    if len(set(scheme_types)) != len(scheme_types):
        raise ValueError("scheme_types must not contain duplicates")
    windows = plan_history_windows(start_date, end_date, max_window_days=max_window_days)
    timestamp = now or datetime.now(timezone.utc)
    created = 0
    existing = 0
    planned = []

    with session_factory.begin() as db:
        for scheme_type in sorted(scheme_types):
            for window in windows:
                key = _checkpoint_key(window, scheme_type)
                current = db.execute(
                    select(NavBackfillCheckpoint).where(NavBackfillCheckpoint.window_key == key)
                ).scalar_one_or_none()
                if current is not None:
                    existing += 1
                    continue
                db.add(NavBackfillCheckpoint(
                    window_key=key,
                    scheme_type=scheme_type,
                    start_date=window.start_date,
                    end_date=window.end_date,
                    source_url=build_amfi_history_url(window, scheme_type),
                    sampling_mode="daily",
                    status="pending",
                    attempts=0,
                    records_valid=0,
                    inserted_rows=0,
                    updated_rows=0,
                    unchanged_rows=0,
                    duplicate_rows=0,
                    invalid_rows=0,
                    created_at=timestamp,
                    updated_at=timestamp,
                ))
                created += 1
                planned.append({
                    "scheme_type": scheme_type,
                    "start_date": window.start_date.isoformat(),
                    "end_date": window.end_date.isoformat(),
                    "window_key": key,
                })
    return {
        "status": "planned",
        "windows_per_scheme_type": len(windows),
        "scheme_types": sorted(scheme_types),
        "checkpoints_created": created,
        "checkpoints_already_present": existing,
        "windows": planned,
        "network_requests_made": 0,
    }



def plan_calendar_month_windows(start_date: date, end_date: date) -> list[HistoryWindow]:
    """Create month-aligned windows; each request stays within AMFI's 90-day cap."""
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date")
    windows: list[HistoryWindow] = []
    cursor = start_date
    while cursor <= end_date:
        last_day = calendar.monthrange(cursor.year, cursor.month)[1]
        month_end = min(date(cursor.year, cursor.month, last_day), end_date)
        windows.append(HistoryWindow(cursor, month_end))
        cursor = month_end + timedelta(days=1)
    return windows


def _monthly_checkpoint_key(window: HistoryWindow, scheme_type: int) -> str:
    raw = (
        f"amfi-nav-history-month-end|type={scheme_type}|"
        f"{window.start_date.isoformat()}|{window.end_date.isoformat()}"
    )
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def create_storage_optimized_history_plan(
    full_start_date: date,
    full_end_date: date,
    monthly_start_date: date,
    daily_start_date: date,
    scheme_types: tuple[int, ...] = (1, 2, 3),
    *,
    session_factory: Callable = SessionLocal,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Replace an all-daily plan with daily recent NAV plus monthly older NAV."""
    if not scheme_types or any(
        not isinstance(value, int) or isinstance(value, bool) or value not in {1, 2, 3}
        for value in scheme_types
    ):
        raise ValueError("scheme_types must contain one or more values from 1, 2, 3")
    if len(set(scheme_types)) != len(scheme_types):
        raise ValueError("scheme_types must not contain duplicates")
    if not full_start_date <= monthly_start_date < daily_start_date <= full_end_date:
        raise ValueError("hybrid plan dates must satisfy full_start <= monthly_start < daily_start <= full_end")

    monthly_end_date = daily_start_date - timedelta(days=1)
    monthly_windows = plan_calendar_month_windows(monthly_start_date, monthly_end_date)
    daily_windows = plan_history_windows(daily_start_date, full_end_date, max_window_days=7)
    timestamp = now or datetime.now(timezone.utc)
    paused = created = reactivated = already_complete = 0

    with session_factory.begin() as db:
        running = db.execute(
            select(NavBackfillCheckpoint.id).where(NavBackfillCheckpoint.status == "running")
        ).first()
        if running is not None:
            raise RuntimeError("Cannot reconfigure history plan while a checkpoint is running")

        unfinished = db.execute(
            select(NavBackfillCheckpoint)
            .where(NavBackfillCheckpoint.status.in_({"pending", "failed"}))
            .with_for_update(skip_locked=True)
        ).scalars().all()
        for row in unfinished:
            row.status = "paused"
            row.error_class = "StorageOptimizedHybridPlan"
            row.completed_at = None
            row.updated_at = timestamp
            paused += 1

        def upsert_window(window: HistoryWindow, scheme_type: int, sampling_mode: str) -> None:
            nonlocal created, reactivated, already_complete
            key = (
                _checkpoint_key(window, scheme_type)
                if sampling_mode == "daily"
                else _monthly_checkpoint_key(window, scheme_type)
            )
            current = db.execute(
                select(NavBackfillCheckpoint).where(NavBackfillCheckpoint.window_key == key)
            ).scalar_one_or_none()
            source_url = build_amfi_history_url(window, scheme_type)
            if current is not None:
                if current.status == "complete":
                    already_complete += 1
                    return
                if current.status == "running":
                    raise RuntimeError("Cannot reconfigure a running history checkpoint")
                current.start_date = window.start_date
                current.end_date = window.end_date
                current.source_url = source_url
                current.sampling_mode = sampling_mode
                current.status = "pending"
                current.error_class = None
                current.completed_at = None
                current.updated_at = timestamp
                reactivated += 1
                return
            db.add(NavBackfillCheckpoint(
                window_key=key,
                scheme_type=scheme_type,
                start_date=window.start_date,
                end_date=window.end_date,
                source_url=source_url,
                sampling_mode=sampling_mode,
                status="pending",
                attempts=0,
                records_valid=0,
                inserted_rows=0,
                updated_rows=0,
                unchanged_rows=0,
                duplicate_rows=0,
                invalid_rows=0,
                created_at=timestamp,
                updated_at=timestamp,
            ))
            created += 1

        for scheme_type in sorted(scheme_types):
            for window in monthly_windows:
                upsert_window(window, scheme_type, "month_end")
            for window in daily_windows:
                upsert_window(window, scheme_type, "daily")

    return {
        "status": "planned",
        "scheme_types": sorted(scheme_types),
        "monthly_start_date": monthly_start_date.isoformat(),
        "monthly_end_date": monthly_end_date.isoformat(),
        "daily_start_date": daily_start_date.isoformat(),
        "daily_end_date": full_end_date.isoformat(),
        "monthly_windows_per_scheme_type": len(monthly_windows),
        "daily_windows_per_scheme_type": len(daily_windows),
        "checkpoints_paused": paused,
        "checkpoints_created": created,
        "checkpoints_reactivated": reactivated,
        "completed_checkpoints_preserved": already_complete,
        "network_requests_made": 0,
    }


def retain_month_end_records(records: list[Any]) -> list[Any]:
    """Keep the latest available NAV for each scheme in each calendar month."""
    latest: dict[tuple[int, int, int], Any] = {}
    for record in records:
        key = (record.scheme_code, record.nav_date.year, record.nav_date.month)
        current = latest.get(key)
        if current is None or record.nav_date > current.nav_date:
            latest[key] = record
    return sorted(
        latest.values(),
        key=lambda record: (record.scheme_code, record.nav_date),
    )


def run_history_backfill_batch(
    limit: int = 1,
    *,
    fetcher: Callable = fetch_amfi_history_window,
    session_factory: Callable = SessionLocal,
    now_factory: Callable = lambda: datetime.now(timezone.utc),
    max_attempts: int = 3,
    enabled: bool = False,
    source_contract_verified: bool = False,
    stale_after_minutes: int = 30,
) -> dict[str, Any]:
    """Run a bounded number of pending/failed windows; each window commits atomically.

    Both flags are explicit release gates. Unit tests and staging harnesses must
    opt in deliberately; the production default is to make no network request.
    """
    if not enabled:
        raise RuntimeError("AMFI historical backfill is disabled; explicit operator enablement is required")
    if not source_contract_verified:
        raise RuntimeError("AMFI historical request contract has not been verified against the official form")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 5:
        raise ValueError("max_attempts must be between 1 and 5")
    if not isinstance(stale_after_minutes, int) or isinstance(stale_after_minutes, bool) or not 1 <= stale_after_minutes <= 240:
        raise ValueError("stale_after_minutes must be between 1 and 240")

    selected: list[tuple[int, HistoryWindow, int, str]] = []
    with session_factory.begin() as db:
        # Recover checkpoints left in running state after a process crash. A
        # running request is never reclaimed until its lease-age threshold.
        stale_before = now_factory() - timedelta(minutes=stale_after_minutes)
        stale_rows = db.execute(
            select(NavBackfillCheckpoint)
            .where(
                NavBackfillCheckpoint.status == "running",
                NavBackfillCheckpoint.updated_at < stale_before,
            )
            .with_for_update(skip_locked=True)
        ).scalars().all()
        for stale in stale_rows:
            stale.status = "failed"
            stale.error_class = "StaleWorkerRecovery"
            stale.completed_at = None
            stale.updated_at = now_factory()

        rows = db.execute(
            select(NavBackfillCheckpoint)
            .where(
                NavBackfillCheckpoint.status.in_({"pending", "failed"}),
                NavBackfillCheckpoint.attempts < max_attempts,
            )
            .order_by(
                NavBackfillCheckpoint.start_date,
                NavBackfillCheckpoint.scheme_type,
                NavBackfillCheckpoint.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).scalars().all()
        for row in rows:
            row.status = "running"
            row.attempts += 1
            row.error_class = None
            row.completed_at = None
            row.updated_at = now_factory()
            selected.append((
                row.id,
                HistoryWindow(row.start_date, row.end_date),
                row.scheme_type,
                row.sampling_mode or "daily",
            ))

    results = []
    completed = failed = 0
    for checkpoint_id, window, scheme_type, sampling_mode in selected:
        try:
            records, report = fetcher(window, scheme_type)
            report = dict(report)
            if sampling_mode == "month_end":
                source_records_valid = len(records)
                records = retain_month_end_records(records)
                if not records:
                    raise ValueError("AMFI month-end window contained no valid scheme NAV observations")
                report["source_records_valid"] = source_records_valid
                report["records_discarded_by_sampling"] = source_records_valid - len(records)
                report["records_valid"] = len(records)
                report["unique_scheme_codes"] = len({record.scheme_code for record in records})
                report["min_nav_date"] = min(record.nav_date for record in records).isoformat()
                report["max_nav_date"] = max(record.nav_date for record in records).isoformat()
            elif sampling_mode != "daily":
                raise ValueError(f"unsupported historical NAV sampling mode: {sampling_mode}")
            report["sampling_mode"] = sampling_mode
            persisted = persist_historical_nav_window(
                checkpoint_id, records, report, now_factory(), session_factory=session_factory
            )
            completed += 1
            results.append({
                "checkpoint_id": checkpoint_id,
                "scheme_type": scheme_type,
                "sampling_mode": sampling_mode,
                "status": "complete",
                **persisted,
            })
        except Exception as exc:
            with session_factory.begin() as db:
                checkpoint = db.get(NavBackfillCheckpoint, checkpoint_id)
                if checkpoint is not None and checkpoint.status == "running":
                    checkpoint.status = "failed"
                    checkpoint.error_class = type(exc).__name__[:120]
                    checkpoint.completed_at = None
                    checkpoint.updated_at = now_factory()
            failed += 1
            original_error = getattr(exc, "orig", None)
            error_text = str(original_error or exc).strip() or type(exc).__name__
            error_detail = error_text.splitlines()[0][:400]
            results.append({
                "checkpoint_id": checkpoint_id,
                "scheme_type": scheme_type,
                "sampling_mode": sampling_mode,
                "status": "failed",
                "error_class": type(exc).__name__,
                "error_detail": error_detail,
            })

    return {
        "status": "completed" if selected and not failed else "partial_failure" if failed else "idle",
        "selected": len(selected),
        "completed": completed,
        "failed": failed,
        "results": results,
        "max_attempts": max_attempts,
    }


def history_backfill_status(*, session_factory: Callable = SessionLocal) -> dict[str, Any]:
    """Return auditable checkpoint counts and persisted NAV totals."""
    with session_factory() as db:
        rows = db.execute(
            select(
                NavBackfillCheckpoint.scheme_type,
                NavBackfillCheckpoint.status,
                func.count(NavBackfillCheckpoint.id),
                func.coalesce(func.sum(NavBackfillCheckpoint.records_valid), 0),
                func.coalesce(func.sum(NavBackfillCheckpoint.inserted_rows), 0),
                func.coalesce(func.sum(NavBackfillCheckpoint.updated_rows), 0),
                func.coalesce(func.sum(NavBackfillCheckpoint.unchanged_rows), 0),
            )
            .group_by(NavBackfillCheckpoint.scheme_type, NavBackfillCheckpoint.status)
            .order_by(NavBackfillCheckpoint.scheme_type, NavBackfillCheckpoint.status)
        ).all()
    return {
        "status": "ok",
        "groups": [
            {
                "scheme_type": row[0],
                "checkpoint_status": row[1],
                "windows": row[2],
                "records_valid": int(row[3]),
                "inserted_rows": int(row[4]),
                "updated_rows": int(row[5]),
                "unchanged_rows": int(row[6]),
            }
            for row in rows
        ],
    }
