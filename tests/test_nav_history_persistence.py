from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from app.db import (
    Base, IngestionSnapshot, NavBackfillCheckpoint, NavObservation,
    Scheme,
)
from app.nav_history_persistence import persist_historical_nav_window


@pytest.fixture
def factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def _seed(factory):
    now = datetime.now(timezone.utc)
    with factory.begin() as db:
        checkpoint = NavBackfillCheckpoint(
            window_key="b" * 64, scheme_type=1,
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 7),
            source_url="https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx",
            status="running", attempts=1, records_valid=0, inserted_rows=0,
            updated_rows=0, unchanged_rows=0, duplicate_rows=0, invalid_rows=0,
            created_at=now, updated_at=now,
        )
        db.add(checkpoint)
        db.flush()
        return checkpoint.id


def _record(nav=Decimal("10.25")):
    return SimpleNamespace(
        scheme_code=119551, scheme_name="Example Fund",
        isin_growth="INF204K01K15", isin_dividend_reinvestment=None,
        nav=nav, nav_date=date(2026, 1, 2), plan_type=None, option_type=None,
    )


def _report():
    return {
        "payload_sha256": "c" * 64, "records_valid": 1,
        "unique_scheme_codes": 1, "min_nav_date": "2026-01-02",
        "max_nav_date": "2026-01-02", "invalid_rows": 0,
        "duplicate_rows_skipped": 0, "quality_status": "PASS",
    }


def test_nav_and_checkpoint_complete_commit_together(factory):
    checkpoint_id = _seed(factory)
    result = persist_historical_nav_window(
        checkpoint_id, [_record()], _report(), datetime.now(timezone.utc),
        session_factory=factory,
    )
    with factory() as db:
        checkpoint = db.get(NavBackfillCheckpoint, checkpoint_id)
        nav = db.execute(select(NavObservation)).scalar_one()
        assert checkpoint.status == "complete"
        assert checkpoint.completed_at is not None
        assert checkpoint.inserted_rows == 1
        assert nav.nav_value == Decimal("10.25000000")
        assert result["inserted_rows"] == 1


def test_failed_nav_write_rolls_back_snapshot_scheme_and_checkpoint(factory):
    checkpoint_id = _seed(factory)
    bad = _record(Decimal("-1"))
    with pytest.raises(Exception):
        persist_historical_nav_window(
            checkpoint_id, [bad], _report(), datetime.now(timezone.utc),
            session_factory=factory,
        )
    with factory() as db:
        checkpoint = db.get(NavBackfillCheckpoint, checkpoint_id)
        assert checkpoint.status == "running"
        assert db.scalar(select(func.count()).select_from(IngestionSnapshot)) == 0
        assert db.scalar(select(func.count()).select_from(Scheme)) == 0
        assert db.scalar(select(func.count()).select_from(NavObservation)) == 0


def test_preserves_existing_isin_when_archive_has_no_isin(factory):
    checkpoint_id = _seed(factory)
    now = datetime.now(timezone.utc)
    with factory.begin() as db:
        db.add(Scheme(
            scheme_code=119551, scheme_name="Old Fund",
            isin_growth="INF204K01K15", isin_dividend_reinvestment="INF204K01K23",
            first_seen_at=now, last_seen_at=now,
        ))
    record = _record()
    record.isin_growth = None
    record.isin_dividend_reinvestment = None
    persist_historical_nav_window(
        checkpoint_id, [record], _report(), now, session_factory=factory,
    )
    with factory() as db:
        scheme = db.get(Scheme, 119551)
        assert scheme.isin_growth == "INF204K01K15"
        assert scheme.isin_dividend_reinvestment == "INF204K01K23"


def test_rejects_checkpoint_outside_running_state(factory):
    checkpoint_id = _seed(factory)
    with factory.begin() as db:
        db.get(NavBackfillCheckpoint, checkpoint_id).status = "failed"
    with pytest.raises(ValueError, match="must be running"):
        persist_historical_nav_window(
            checkpoint_id, [_record()], _report(), datetime.now(timezone.utc),
            session_factory=factory,
        )
