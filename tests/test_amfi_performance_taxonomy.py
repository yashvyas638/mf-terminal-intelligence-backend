from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.amfi_performance_taxonomy import canonicalize_performance_rows
from app.db import Base, IngestionSnapshot, NavObservation, Scheme
from app.scheme_metadata import refresh_scheme_taxonomy


def test_canonicalizes_explicit_amfi_scheme_code_and_allowlisted_category():
    mappings, rejected = canonicalize_performance_rows(
        [{"Scheme_Code": "119551", "Scheme_Name": "Example Fund"}],
        category_group="Equity Scheme",
        subcategory="Flexi Cap Fund",
    )
    assert mappings == {
        119551: {
            "category_group": "Equity Scheme",
            "category": "Flexi Cap Fund",
        }
    }
    assert rejected == 0


def test_unknown_amfi_subcategory_fails_closed():
    mappings, rejected = canonicalize_performance_rows(
        [{"Scheme_Code": "119551"}],
        category_group="Equity Scheme",
        subcategory="Legacy Solution Oriented Fund",
    )
    assert mappings == {}
    assert rejected == 1


def test_invalid_scheme_codes_are_rejected():
    mappings, rejected = canonicalize_performance_rows(
        [{"Scheme_Code": "not-a-code"}, {"Scheme_Code": "-1"}],
        category_group="Equity Scheme",
        subcategory="Flexi Cap Fund",
    )
    assert mappings == {}
    assert rejected == 2


def test_conflicting_rows_for_same_scheme_are_rejected():
    with pytest.raises(ValueError, match="conflicting categories"):
        canonicalize_performance_rows(
            [{"Scheme_Code": "119551"}, {"Scheme_Code": "119551"}],
            category_group="Equity Scheme",
            subcategory="Flexi Cap Fund",
        )


def test_taxonomy_refresh_only_fills_active_missing_categories_and_never_overwrites_valid_data():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    try:
        with factory.begin() as db:
            snapshot = IngestionSnapshot(
                source_url="https://portal.amfiindia.com/spages/NAVAll.txt",
                retrieved_at=now,
                payload_sha256="a" * 64,
                records_valid=2,
                unique_scheme_codes=2,
                min_nav_date=date.today(),
                max_nav_date=date.today(),
                invalid_rows=0,
                duplicate_rows_skipped=0,
                quality_status="PASS",
                report_json="{}",
            )
            db.add(snapshot)
            db.flush()
            db.add_all([
                Scheme(
                    scheme_code=119551,
                    scheme_name="Missing Category Fund",
                    first_seen_at=now,
                    last_seen_at=now,
                    category_group="Equity Scheme",
                    category=None,
                    asset_class="Equity",
                ),
                Scheme(
                    scheme_code=119552,
                    scheme_name="Already Classified Fund",
                    first_seen_at=now,
                    last_seen_at=now,
                    category_group="Equity Scheme",
                    category="Large Cap Fund",
                    asset_class="Equity",
                ),
                Scheme(
                    scheme_code=119553,
                    scheme_name="Inactive Fund",
                    first_seen_at=now,
                    last_seen_at=now,
                ),
            ])
            db.flush()
            db.add_all([
                NavObservation(
                    scheme_code=119551,
                    nav_date=date.today(),
                    nav_value="10.0",
                    source_snapshot_id=snapshot.id,
                ),
                NavObservation(
                    scheme_code=119552,
                    nav_date=date.today(),
                    nav_value="20.0",
                    source_snapshot_id=snapshot.id,
                ),
            ])

        result = refresh_scheme_taxonomy(
            {
                119551: {
                    "category_group": "Equity Scheme",
                    "category": "Flexi Cap Fund",
                },
                119552: {
                    "category_group": "Equity Scheme",
                    "category": "Flexi Cap Fund",
                },
                119553: {
                    "category_group": "Equity Scheme",
                    "category": "Mid Cap Fund",
                },
            },
            now,
            session_factory=factory,
        )
        with factory() as db:
            missing = db.get(Scheme, 119551)
            existing = db.get(Scheme, 119552)
            inactive = db.get(Scheme, 119553)
            assert missing.category_group == "Equity Scheme"
            assert missing.category == "Flexi Cap Fund"
            assert missing.asset_class == "Equity"
            assert existing.category == "Large Cap Fund"
            assert inactive.category is None

        assert result["category_rows_updated"] == 1
        assert result["source_conflicts"] == 1
        assert result["not_active_in_nav_window"] == 1
    finally:
        engine.dispose()
