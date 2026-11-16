from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, IngestionSnapshot, NavObservation, Scheme
from app.scheme_metadata import refresh_scheme_taxonomy


def _factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _seed_scheme(factory, code, *, name, amc="Example AMC", group=None, category=None):
    now = datetime.now(timezone.utc)
    with factory.begin() as db:
        snapshot = IngestionSnapshot(
            source_url="https://example.test/nav",
            retrieved_at=now,
            payload_sha256="a" * 64,
            records_valid=1,
            unique_scheme_codes=1,
            min_nav_date=date(2026, 11, 12),
            max_nav_date=date(2026, 11, 12),
            invalid_rows=0,
            duplicate_rows_skipped=0,
            quality_status="PASS",
            report_json="{}",
        )
        db.add(snapshot)
        db.flush()
        db.add(Scheme(
            scheme_code=code,
            scheme_name=name,
            first_seen_at=now,
            last_seen_at=now,
            amc=amc,
            category_group=group,
            category=category,
            asset_class="Equity" if group == "Equity Scheme" else None,
        ))
        db.add(NavObservation(
            scheme_code=code,
            nav_date=date(2026, 11, 12),
            nav_value=Decimal("10.0"),
            source_snapshot_id=snapshot.id,
        ))


def test_taxonomy_refresh_fills_exact_name_matches_across_plan_variants():
    engine, factory = _factory()
    try:
        _seed_scheme(
            factory, 1001,
            name="Example Fund - Direct Plan - Growth",
            group=None,
            category=None,
        )
        _seed_scheme(
            factory, 1002,
            name="Example Fund - Regular Plan - Growth",
            group=None,
            category=None,
        )

        result = refresh_scheme_taxonomy(
            {"name:example fund": {
                "category_group": "Equity Scheme",
                "category": "Thematic Fund",
                "asset_class": "Equity",
            }},
            datetime(2026, 11, 13, tzinfo=timezone.utc),
            session_factory=factory,
        )

        with factory() as db:
            schemes = [db.get(Scheme, code) for code in (1001, 1002)]
            assert [(s.category_group, s.category, s.asset_class) for s in schemes] == [
                ("Equity Scheme", "Thematic Fund", "Equity"),
                ("Equity Scheme", "Thematic Fund", "Equity"),
            ]
        assert result["active_schemes_scanned"] == 2
        assert result["category_rows_updated"] == 2
        assert result["source_conflicts"] == 0
    finally:
        engine.dispose()


def test_taxonomy_refresh_does_not_overwrite_conflicting_group_or_category():
    engine, factory = _factory()
    try:
        _seed_scheme(
            factory, 2001,
            name="Debt Example Fund - Direct Plan - Growth",
            group="Debt Scheme",
            category=None,
        )
        _seed_scheme(
            factory, 2002,
            name="Equity Example Fund - Direct Plan - Growth",
            group="Equity Scheme",
            category="Large Cap Fund",
        )

        result = refresh_scheme_taxonomy(
            {
                "name:debt example fund": {
                    "category_group": "Equity Scheme",
                    "category": "Thematic Fund",
                    "asset_class": "Equity",
                },
                "name:equity example fund": {
                    "category_group": "Equity Scheme",
                    "category": "Thematic Fund",
                    "asset_class": "Equity",
                },
            },
            datetime(2026, 11, 13, tzinfo=timezone.utc),
            session_factory=factory,
        )

        with factory() as db:
            debt = db.get(Scheme, 2001)
            equity = db.get(Scheme, 2002)
            assert (debt.category_group, debt.category) == ("Debt Scheme", None)
            assert (equity.category_group, equity.category) == ("Equity Scheme", "Large Cap Fund")
        assert result["category_rows_updated"] == 0
        assert result["source_conflicts"] == 2
    finally:
        engine.dispose()


def test_taxonomy_refresh_refines_combined_sectoral_thematic_only_when_verified():
    engine, factory = _factory()
    try:
        _seed_scheme(
            factory, 3001,
            name="Example Theme Fund - Direct Plan - Growth",
            group="Equity Scheme",
            category="Sectoral/Thematic Fund",
        )
        mapping = {"name:example theme fund": {
            "category_group": "Equity Scheme",
            "category": "Thematic Fund",
            "asset_class": "Equity",
        }}

        blocked = refresh_scheme_taxonomy(
            mapping,
            datetime(2026, 11, 13, tzinfo=timezone.utc),
            session_factory=factory,
            allow_verified_refinements=False,
        )
        with factory() as db:
            assert db.get(Scheme, 3001).category == "Sectoral/Thematic Fund"
        assert blocked["category_rows_updated"] == 0
        assert blocked["source_conflicts"] == 1

        allowed = refresh_scheme_taxonomy(
            mapping,
            datetime(2026, 11, 13, tzinfo=timezone.utc),
            session_factory=factory,
            allow_verified_refinements=True,
        )
        with factory() as db:
            assert db.get(Scheme, 3001).category == "Thematic Fund"
        assert allowed["category_rows_updated"] == 1
        assert allowed["source_conflicts"] == 0
    finally:
        engine.dispose()


def test_taxonomy_refresh_skips_exact_name_shared_by_multiple_amcs():
    engine, factory = _factory()
    try:
        _seed_scheme(
            factory, 4001,
            name="Shared Scheme - Direct Plan - Growth",
            amc="AMC One",
        )
        _seed_scheme(
            factory, 4002,
            name="Shared Scheme - Regular Plan - Growth",
            amc="AMC Two",
        )

        result = refresh_scheme_taxonomy(
            {"name:shared scheme": {
                "category_group": "Equity Scheme",
                "category": "Thematic Fund",
                "asset_class": "Equity",
            }},
            datetime(2026, 11, 13, tzinfo=timezone.utc),
            session_factory=factory,
        )

        with factory() as db:
            assert db.get(Scheme, 4001).category is None
            assert db.get(Scheme, 4002).category is None
        assert result["active_schemes_scanned"] == 0
        assert result["category_rows_updated"] == 0
        assert result["source_names_ambiguous"] == 1
    finally:
        engine.dispose()
