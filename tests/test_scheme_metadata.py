from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, Scheme
from app.scheme_metadata import refresh_scheme_metadata


def _factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, factory


def _record(
    code=119551,
    *,
    category_group="Equity Scheme",
    category="Large Cap Fund",
    asset_class="Equity",
    metadata_present=True,
    plan_type="Direct Plan",
    option_type="Growth",
    amc="Example Mutual Fund",
):
    return SimpleNamespace(
        scheme_code=code,
        scheme_name="Example Large Cap Fund - Direct Plan - Growth",
        isin_growth="INF204K01K15",
        isin_dividend_reinvestment=None,
        nav=Decimal("10.25"),
        nav_date=date(2026, 11, 11),
        plan_type=plan_type,
        option_type=option_type,
        amc=amc,
        structure="Open Ended" if metadata_present else None,
        category_group=category_group,
        category=category,
        asset_class=asset_class,
        metadata_present=metadata_present,
    )


def test_metadata_refresh_creates_and_classifies_missing_scheme():
    engine, factory = _factory()
    try:
        result = refresh_scheme_metadata(
            [_record()], datetime.now(timezone.utc), session_factory=factory
        )
        with factory() as db:
            scheme = db.get(Scheme, 119551)
            assert scheme is not None
            assert scheme.category_group == "Equity Scheme"
            assert scheme.category == "Large Cap Fund"
            assert scheme.asset_class == "Equity"
            assert scheme.plan_type == "Direct Plan"
            assert scheme.option_type == "Growth"
            assert scheme.amc == "Example Mutual Fund"
        assert result["scheme_rows_created"] == 1
        assert result["category_group_populated"] == 1
    finally:
        engine.dispose()


def test_metadata_refresh_updates_existing_scheme_and_clears_explicit_unknown_category():
    engine, factory = _factory()
    now = datetime.now(timezone.utc)
    try:
        with factory.begin() as db:
            db.add(Scheme(
                scheme_code=119551,
                scheme_name="Old Marketing Label",
                first_seen_at=now,
                last_seen_at=now,
                category_group="Equity Scheme",
                category="Large Cap Fund",
                asset_class="Equity",
            ))
        result = refresh_scheme_metadata(
            [_record(category_group=None, category=None, asset_class=None)],
            now,
            session_factory=factory,
        )
        with factory() as db:
            scheme = db.get(Scheme, 119551)
            assert scheme.category_group is None
            assert scheme.category is None
            assert scheme.asset_class is None
            assert scheme.plan_type == "Direct Plan"
            assert scheme.option_type == "Growth"
        assert result["scheme_rows_updated"] == 1
        assert result["category_unclassified"] == 1
    finally:
        engine.dispose()


def test_metadata_refresh_does_not_erase_categories_when_no_category_section_was_seen():
    engine, factory = _factory()
    now = datetime.now(timezone.utc)
    try:
        with factory.begin() as db:
            db.add(Scheme(
                scheme_code=119551,
                scheme_name="Old Marketing Label",
                first_seen_at=now,
                last_seen_at=now,
                category_group="Equity Scheme",
                category="Large Cap Fund",
                asset_class="Equity",
            ))
        refresh_scheme_metadata(
            [_record(metadata_present=False, category_group=None, category=None, asset_class=None)],
            now,
            session_factory=factory,
        )
        with factory() as db:
            scheme = db.get(Scheme, 119551)
            assert scheme.category_group == "Equity Scheme"
            assert scheme.category == "Large Cap Fund"
            assert scheme.asset_class == "Equity"
    finally:
        engine.dispose()


def test_metadata_refresh_uses_one_latest_record_per_scheme_code():
    engine, factory = _factory()
    try:
        older = _record()
        newer = _record(category="Flexi Cap Fund")
        newer.nav_date = date(2026, 11, 12)
        result = refresh_scheme_metadata(
            [older, newer], datetime.now(timezone.utc), session_factory=factory
        )
        with factory() as db:
            scheme = db.get(Scheme, 119551)
            assert scheme.category == "Flexi Cap Fund"
            assert db.scalar(select(func.count()).select_from(Scheme)) == 1
        assert result["scheme_records_seen"] == 1
    finally:
        engine.dispose()
