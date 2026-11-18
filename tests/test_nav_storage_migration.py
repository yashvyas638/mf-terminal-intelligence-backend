import pytest
from sqlalchemy import text

from app.db import Base, NavObservation, engine


def test_nav_observation_metadata_does_not_declare_duplicate_index():
    index_names = {index.name for index in NavObservation.__table__.indexes}
    assert "ix_nav_code_date" not in index_names
    assert "uq_nav_scheme_date" in {
        constraint.name for constraint in NavObservation.__table__.constraints
    }


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostgreSQL-specific")
def test_nav_lookup_index_migration_retains_unique_lookup_index():
    with engine.connect() as connection:
        duplicate = connection.execute(text(
            "SELECT 1 FROM pg_indexes "
            "WHERE schemaname='public' AND tablename='nav_observations' "
            "AND indexname='ix_nav_code_date'"
        )).scalar_one_or_none()
        unique = connection.execute(text(
            "SELECT 1 FROM pg_constraint "
            "WHERE conrelid='public.nav_observations'::regclass "
            "AND conname='uq_nav_scheme_date' AND contype='u'"
        )).scalar_one_or_none()
    assert duplicate is None
    assert unique == 1
