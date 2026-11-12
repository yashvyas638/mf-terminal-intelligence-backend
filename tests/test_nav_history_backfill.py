from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, NavBackfillCheckpoint, NavObservation
from app.nav_history_backfill import (
    create_history_backfill_plan,
    create_storage_optimized_history_plan,
    history_backfill_status,
    plan_calendar_month_windows,
    retain_month_end_records,
    run_history_backfill_batch,
)


@pytest.fixture
def factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def _record():
    return SimpleNamespace(
        scheme_code=119551,
        scheme_name="Example Fund",
        isin_growth="INF204K01K15",
        isin_dividend_reinvestment=None,
        nav=Decimal("10.25"),
        nav_date=date(2026, 1, 2),
        plan_type=None,
        option_type=None,
    )


def _report():
    return {
        "payload_sha256": "a" * 64,
        "records_valid": 1,
        "unique_scheme_codes": 1,
        "min_nav_date": "2026-01-02",
        "max_nav_date": "2026-01-02",
        "invalid_rows": 0,
        "duplicate_rows_skipped": 0,
        "quality_status": "PASS",
    }


def test_plan_is_idempotent_and_scheme_type_is_part_of_checkpoint_key(factory):
    first = create_history_backfill_plan(
        date(2026, 1, 1), date(2026, 1, 7), (1, 2), session_factory=factory
    )
    second = create_history_backfill_plan(
        date(2026, 1, 1), date(2026, 1, 7), (1, 2), session_factory=factory
    )
    assert first["checkpoints_created"] == 2
    assert second["checkpoints_created"] == 0
    assert second["checkpoints_already_present"] == 2
    with factory() as db:
        rows = db.execute(select(NavBackfillCheckpoint)).scalars().all()
        assert len(rows) == 2
        assert {row.scheme_type for row in rows} == {1, 2}
        assert len({row.window_key for row in rows}) == 2


def test_default_plan_uses_seven_day_windows(factory):
    result = create_history_backfill_plan(
        date(2026, 1, 1), date(2026, 1, 16), (1,), session_factory=factory
    )
    assert result["windows_per_scheme_type"] == 3
    with factory() as db:
        rows = db.execute(select(NavBackfillCheckpoint).order_by(NavBackfillCheckpoint.start_date)).scalars().all()
        assert [(row.start_date, row.end_date) for row in rows] == [
            (date(2026, 1, 1), date(2026, 1, 7)),
            (date(2026, 1, 8), date(2026, 1, 14)),
            (date(2026, 1, 15), date(2026, 1, 16)),
        ]


def test_batch_commits_nav_and_checkpoint_then_status_reports_totals(factory):
    create_history_backfill_plan(
        date(2026, 1, 1), date(2026, 1, 7), (1,), session_factory=factory
    )
    result = run_history_backfill_batch(
        limit=1,
        fetcher=lambda window, scheme_type: ([_record()], _report()),
        session_factory=factory,
        enabled=True,
        source_contract_verified=True,
    )
    assert result["completed"] == 1
    assert result["failed"] == 0
    with factory() as db:
        checkpoint = db.execute(select(NavBackfillCheckpoint)).scalar_one()
        nav = db.execute(select(NavObservation)).scalar_one()
        assert checkpoint.status == "complete"
        assert checkpoint.attempts == 1
        assert checkpoint.completed_at is not None
        assert nav.nav_value == Decimal("10.25000000")
    status = history_backfill_status(session_factory=factory)
    assert status["groups"][0]["records_valid"] == 1
    assert status["groups"][0]["inserted_rows"] == 1


def test_failed_window_is_recorded_and_can_be_retried(factory):
    create_history_backfill_plan(
        date(2026, 1, 1), date(2026, 1, 7), (1,), session_factory=factory
    )
    failed = run_history_backfill_batch(
        fetcher=lambda window, scheme_type: (_ for _ in ()).throw(TimeoutError()),
        session_factory=factory,
        enabled=True,
        source_contract_verified=True,
    )
    assert failed["failed"] == 1
    with factory() as db:
        checkpoint = db.execute(select(NavBackfillCheckpoint)).scalar_one()
        assert checkpoint.status == "failed"
        assert checkpoint.error_class == "TimeoutError"
        assert checkpoint.attempts == 1

    retried = run_history_backfill_batch(
        fetcher=lambda window, scheme_type: ([_record()], _report()),
        session_factory=factory,
        enabled=True,
        source_contract_verified=True,
    )
    assert retried["completed"] == 1
    with factory() as db:
        checkpoint = db.execute(select(NavBackfillCheckpoint)).scalar_one()
        assert checkpoint.status == "complete"
        assert checkpoint.attempts == 2


def test_empty_or_invalid_batch_limits_are_rejected(factory):
    with pytest.raises(ValueError, match="limit"):
        run_history_backfill_batch(
            limit=0, session_factory=factory, enabled=True, source_contract_verified=True
        )
    with pytest.raises(ValueError, match="scheme_types"):
        create_history_backfill_plan(
            date(2026, 1, 1), date(2026, 1, 7), (), session_factory=factory
        )


def test_backfill_is_disabled_without_both_explicit_release_gates(factory):
    with pytest.raises(RuntimeError, match="disabled"):
        run_history_backfill_batch(session_factory=factory, source_contract_verified=True)
    with pytest.raises(RuntimeError, match="not been verified"):
        run_history_backfill_batch(session_factory=factory, enabled=True)


def test_stale_running_checkpoint_is_recovered_after_worker_crash(factory):
    now = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
    create_history_backfill_plan(
        date(2026, 1, 1), date(2026, 1, 7), (1,),
        session_factory=factory, now=now - timedelta(hours=1),
    )
    with factory.begin() as db:
        checkpoint = db.execute(select(NavBackfillCheckpoint)).scalar_one()
        checkpoint.status = "running"
        checkpoint.attempts = 1
        checkpoint.updated_at = now - timedelta(hours=1)

    recovered = run_history_backfill_batch(
        fetcher=lambda window, scheme_type: ([_record()], _report()),
        session_factory=factory,
        now_factory=lambda: now,
        max_attempts=1,
        enabled=True,
        source_contract_verified=True,
    )
    # The abandoned claim is refunded and retried in the same bounded batch.
    assert recovered["selected"] == 1
    assert recovered["completed"] == 1
    with factory() as db:
        checkpoint = db.execute(select(NavBackfillCheckpoint)).scalar_one()
        assert checkpoint.status == "complete"
        assert checkpoint.error_class is None
        assert checkpoint.attempts == 1



def test_calendar_month_windows_are_aligned_and_never_exceed_31_days():
    windows = plan_calendar_month_windows(date(2021, 11, 19), date(2022, 1, 31))
    assert [(item.start_date, item.end_date) for item in windows] == [
        (date(2021, 11, 19), date(2021, 11, 30)),
        (date(2021, 12, 1), date(2021, 12, 31)),
        (date(2022, 1, 1), date(2022, 1, 31)),
    ]
    assert all(item.day_count <= 31 for item in windows)


def test_month_end_sampling_keeps_latest_nav_per_scheme_and_month():
    records = [
        SimpleNamespace(scheme_code=1, nav_date=date(2021, 12, 1), nav=Decimal("10")),
        SimpleNamespace(scheme_code=1, nav_date=date(2021, 12, 30), nav=Decimal("11")),
        SimpleNamespace(scheme_code=2, nav_date=date(2021, 12, 29), nav=Decimal("20")),
        SimpleNamespace(scheme_code=1, nav_date=date(2022, 1, 3), nav=Decimal("12")),
    ]
    sampled = retain_month_end_records(records)
    assert [(item.scheme_code, item.nav_date) for item in sampled] == [
        (1, date(2021, 12, 30)),
        (1, date(2022, 1, 3)),
        (2, date(2021, 12, 29)),
    ]


def test_hybrid_plan_pauses_old_daily_windows_and_preserves_completed_checkpoint(factory):
    create_history_backfill_plan(
        date(2021, 11, 12), date(2026, 11, 11), (1, 2, 3), session_factory=factory
    )
    with factory.begin() as db:
        first = db.execute(
            select(NavBackfillCheckpoint)
            .where(
                NavBackfillCheckpoint.scheme_type == 1,
                NavBackfillCheckpoint.start_date == date(2021, 11, 12),
            )
        ).scalar_one()
        first.status = "complete"
        first.completed_at = datetime(2026, 11, 12, tzinfo=timezone.utc)

    result = create_storage_optimized_history_plan(
        date(2021, 10, 1),
        date(2026, 11, 11),
        date(2021, 11, 19),
        date(2025, 11, 1),
        (1, 2, 3),
        session_factory=factory,
    )
    assert result["checkpoints_paused"] == 782
    assert result["baseline_daily_windows_per_scheme_type"] == 2
    assert result["monthly_windows_per_scheme_type"] == 48
    assert result["daily_windows_per_scheme_type"] == 54
    assert result["checkpoints_created"] == 309
    assert result["checkpoints_reactivated"] == 2
    assert result["completed_checkpoints_preserved"] == 1

    with factory() as db:
        rows = db.execute(select(NavBackfillCheckpoint)).scalars().all()
        assert len(rows) == 783 + 309
        complete = [row for row in rows if row.status == "complete"]
        paused = [row for row in rows if row.status == "paused"]
        pending = [row for row in rows if row.status == "pending"]
        assert len(complete) == 1
        assert len(paused) == 780
        assert len(pending) == 311
        assert sum(row.sampling_mode == "month_end" and row.status == "pending" for row in rows) == 144
        assert sum(row.sampling_mode == "daily" and row.status == "pending" for row in rows) == 167


def test_month_end_batch_persists_only_latest_observation_per_scheme_month(factory):
    create_storage_optimized_history_plan(
        date(2021, 10, 1),
        date(2026, 11, 11),
        date(2021, 11, 19),
        date(2025, 11, 1),
        (1,),
        session_factory=factory,
    )
    # Isolate the month-end sampler test from the full-resolution baseline batch.
    with factory.begin() as db:
        baseline = db.execute(
            select(NavBackfillCheckpoint).where(
                NavBackfillCheckpoint.sampling_mode == "daily",
                NavBackfillCheckpoint.start_date < date(2021, 11, 19),
            )
        ).scalars().all()
        for checkpoint in baseline:
            checkpoint.status = "complete"
            checkpoint.completed_at = datetime(2026, 11, 12, tzinfo=timezone.utc)
    source_records = [
        SimpleNamespace(
            scheme_code=119551,
            scheme_name="Example Fund",
            isin_growth="INF204K01K15",
            isin_dividend_reinvestment=None,
            nav=Decimal("10.10"),
            nav_date=date(2021, 11, 22),
            plan_type="Direct Plan",
            option_type="GROWTH",
        ),
        SimpleNamespace(
            scheme_code=119551,
            scheme_name="Example Fund",
            isin_growth="INF204K01K15",
            isin_dividend_reinvestment=None,
            nav=Decimal("10.25"),
            nav_date=date(2021, 11, 30),
            plan_type="Direct Plan",
            option_type="GROWTH",
        ),
        SimpleNamespace(
            scheme_code=120000,
            scheme_name="Other Fund",
            isin_growth="INF0000000001",
            isin_dividend_reinvestment=None,
            nav=Decimal("20.25"),
            nav_date=date(2021, 11, 29),
            plan_type="Regular Plan",
            option_type="IDCW Payout",
        ),
    ]
    report = {
        **_report(),
        "records_valid": 3,
        "unique_scheme_codes": 2,
        "min_nav_date": "2021-11-22",
        "max_nav_date": "2021-11-30",
    }
    result = run_history_backfill_batch(
        limit=1,
        fetcher=lambda window, scheme_type: (source_records, report),
        session_factory=factory,
        enabled=True,
        source_contract_verified=True,
    )
    assert result["completed"] == 1
    with factory() as db:
        checkpoint = db.execute(
            select(NavBackfillCheckpoint).where(
                NavBackfillCheckpoint.sampling_mode == "month_end",
                NavBackfillCheckpoint.start_date == date(2021, 11, 19),
                NavBackfillCheckpoint.end_date == date(2021, 11, 30),
            )
        ).scalar_one()
        nav_rows = db.execute(select(NavObservation).order_by(NavObservation.scheme_code)).scalars().all()
        assert checkpoint.records_valid == 2
        assert len(nav_rows) == 2
        assert {row.nav_value for row in nav_rows} == {
            Decimal("10.25000000"),
            Decimal("20.25000000"),
        }



def test_hybrid_baseline_windows_create_missing_and_reactivate_only_paused(factory):
    from app.nav_history_backfill import ensure_hybrid_baseline_windows

    # A completed baseline is immutable; a paused one must be reactivated.
    monthly_start = date(2021, 11, 19)
    result = create_storage_optimized_history_plan(
        date(2012, 2, 17),
        date(2026, 11, 11),
        monthly_start,
        date(2025, 11, 19),
        (1, 2, 3),
        session_factory=factory,
        now=datetime(2026, 11, 12, tzinfo=timezone.utc),
    )
    with factory.begin() as db:
        rows = db.execute(
            select(NavBackfillCheckpoint).where(
                NavBackfillCheckpoint.sampling_mode == "daily",
                NavBackfillCheckpoint.start_date.in_({
                    date(2021, 11, 5), date(2021, 11, 12)
                }),
            )
        ).scalars().all()
        # Simulate a previous plan transition that paused the required windows.
        for row in rows:
            row.status = "paused"
    refreshed = ensure_hybrid_baseline_windows(
        monthly_start,
        (1, 2, 3),
        session_factory=factory,
        now=datetime(2026, 11, 13, tzinfo=timezone.utc),
    )
    assert refreshed["baseline_windows_per_scheme_type"] == 2
    assert refreshed["checkpoints_reactivated"] == 6
    assert refreshed["checkpoints_created"] == 0
    with factory() as db:
        rows = db.execute(
            select(NavBackfillCheckpoint).where(
                NavBackfillCheckpoint.sampling_mode == "daily",
                NavBackfillCheckpoint.start_date.in_({
                    date(2021, 11, 5), date(2021, 11, 12)
                }),
            )
        ).scalars().all()
        assert len(rows) == 6
        assert {row.status for row in rows} == {"pending"}


def test_hybrid_baseline_windows_are_idempotent_and_preserve_complete(factory):
    from app.nav_history_backfill import ensure_hybrid_baseline_windows

    monthly_start = date(2021, 11, 19)
    first = ensure_hybrid_baseline_windows(
        monthly_start, (1, 2, 3), session_factory=factory
    )
    assert first["checkpoints_created"] == 6
    second = ensure_hybrid_baseline_windows(
        monthly_start, (1, 2, 3), session_factory=factory
    )
    assert second["checkpoints_created"] == 0
    assert second["checkpoints_preserved"] == 6
