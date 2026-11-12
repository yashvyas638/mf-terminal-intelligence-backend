from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, NavBackfillCheckpoint, NavObservation
from app.nav_history_backfill import (
    create_history_backfill_plan,
    history_backfill_status,
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
    assert recovered["selected"] == 0
    with factory() as db:
        checkpoint = db.execute(select(NavBackfillCheckpoint)).scalar_one()
        assert checkpoint.status == "failed"
        assert checkpoint.error_class == "StaleWorkerRecovery"

    resumed = run_history_backfill_batch(
        fetcher=lambda window, scheme_type: ([_record()], _report()),
        session_factory=factory,
        now_factory=lambda: now,
        max_attempts=2,
        enabled=True,
        source_contract_verified=True,
    )
    assert resumed["completed"] == 1
    with factory() as db:
        checkpoint = db.execute(select(NavBackfillCheckpoint)).scalar_one()
        assert checkpoint.status == "complete"
        assert checkpoint.attempts == 2
