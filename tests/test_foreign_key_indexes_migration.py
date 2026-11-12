from sqlalchemy import create_engine, inspect

from app.db import database_url


def test_foreign_key_lookup_indexes_exist_after_alembic_upgrade():
    engine = create_engine(database_url())
    try:
        inspector = inspect(engine)
        expected = {
            "fund_holding_disclosures": {
                "ix_fund_holding_disclosures_supersedes_id": ["supersedes_disclosure_id"],
            },
            "fund_watchlist_items": {
                "ix_fund_watchlist_items_scheme_code": ["scheme_code"],
            },
            "scheme_benchmark_assignments": {
                "ix_scheme_benchmark_assignments_benchmark_code": ["benchmark_code"],
            },
        }
        for table_name, indexes in expected.items():
            actual = {item["name"]: item["column_names"] for item in inspector.get_indexes(table_name)}
            for index_name, columns in indexes.items():
                assert actual.get(index_name) == columns
    finally:
        engine.dispose()
