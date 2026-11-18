from sqlalchemy import create_engine, inspect

from app.db import database_url


def test_nav_observations_keep_unique_lookup_and_remove_duplicate_index():
    engine = create_engine(database_url())
    try:
        inspector = inspect(engine)
        indexes = {item["name"]: item for item in inspector.get_indexes("nav_observations")}
        unique_constraints = {
            item["name"]: item
            for item in inspector.get_unique_constraints("nav_observations")
        }

        assert "ix_nav_code_date" not in indexes
        assert "uq_nav_scheme_date" in unique_constraints
        assert unique_constraints["uq_nav_scheme_date"]["column_names"] == [
            "scheme_code",
            "nav_date",
        ]
        assert "nav_observations_pkey" in indexes
    finally:
        engine.dispose()
