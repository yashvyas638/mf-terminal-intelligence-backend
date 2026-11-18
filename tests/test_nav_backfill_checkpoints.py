from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db import Base, NavBackfillCheckpoint


def _checkpoint(**overrides):
    values = {
        "window_key": "a" * 64,
        "scheme_type": 1,
        "start_date": date(2026, 1, 1),
        "end_date": date(2026, 1, 7),
        "source_url": "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx",
        "status": "pending",
        "attempts": 0,
        "records_valid": 0,
        "inserted_rows": 0,
        "updated_rows": 0,
        "unchanged_rows": 0,
        "duplicate_rows": 0,
        "invalid_rows": 0,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    values.update(overrides)
    return NavBackfillCheckpoint(**values)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        yield db
    engine.dispose()


def test_checkpoint_persists_window_state_and_resume_metadata(session):
    row = _checkpoint(status="failed", attempts=2, error_class="ReadTimeout")
    session.add(row)
    session.commit()
    loaded = session.query(NavBackfillCheckpoint).one()
    assert loaded.window_key == "a" * 64
    assert loaded.status == "failed"
    assert loaded.attempts == 2
    assert loaded.completed_at is None


def test_window_key_is_unique(session):
    session.add_all([_checkpoint(), _checkpoint()])
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize("overrides", [
    {"scheme_type": 4},
    {"end_date": date(2025, 12, 31)},
    {"status": "done"},
    {"attempts": -1},
    {"records_valid": -1},
    {"status": "complete"},
])
def test_database_rejects_invalid_checkpoint_state(session, overrides):
    session.add(_checkpoint(**overrides))
    with pytest.raises(IntegrityError):
        session.commit()


def test_completed_checkpoint_requires_completion_timestamp(session):
    completed_at = datetime.now(timezone.utc)
    row = _checkpoint(status="complete", completed_at=completed_at)
    session.add(row)
    session.commit()
    assert session.query(NavBackfillCheckpoint).one().completed_at is not None
