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
    from app.amfi_performance_taxonomy import fetch_amfi_performance_taxonomy

    class ConflictingSession(_FakeSession):
        def post(self, url, *, json, timeout):
            if url.endswith("/api/amfi/getsubcategory"):
                return super().post(url, json=json, timeout=timeout)
            return _FakeResponse({
                "data": [{"Scheme_Code": "119551", "Scheme_Name": "Conflicting category"}]
            })

    with pytest.raises(ValueError, match="conflicting categories"):
        fetch_amfi_performance_taxonomy(
            session=ConflictingSession(),
            max_requests=20,
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



class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None

    def close(self):
        return None


class _FakeSession:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def post(self, url, *, json, timeout):
        self.calls.append((url, json, timeout))
        if url.endswith("/api/amfi/getsubcategory"):
            labels = {
                1: (11, "Flexi Cap Fund"),
                2: (22, "Liquid Fund"),
                3: (33, "Arbitrage Fund"),
                5: (55, "Index Funds"),
            }
            category_id = json["category"]
            if category_id not in labels:
                return _FakeResponse({"data": []})
            sub_id, name = labels[category_id]
            return _FakeResponse({"data": [{"id": sub_id, "name": name}]})
        category_id = json["category"]
        codes = {1: "119551", 2: "120503", 3: "130001", 5: "140001"}
        return _FakeResponse({
            "data": [{"Scheme_Code": codes[category_id], "Scheme_Name": "AMFI test"}]
        })


def test_fetches_current_amfi_performance_categories_with_latest_business_date():
    from app.amfi_performance_taxonomy import fetch_amfi_performance_taxonomy

    session = _FakeSession()
    result = fetch_amfi_performance_taxonomy(session=session, max_requests=20)

    assert result["scheme_codes"] == 4
    assert result["requests_made"] == 12
    assert result["performance_rows"] == 8
    assert result["mappings"][119551]["category"] == "Flexi Cap Fund"
    assert result["mappings"][120503]["category_group"] == "Debt Scheme"
    assert result["mappings"][130001]["category"] == "Arbitrage Fund"
    assert result["mappings"][140001]["category"] == "Index Funds / ETFs"
    assert all(call[1].get("category") != 4 for call in session.calls)
    performance_calls = [
        call[1] for call in session.calls
        if call[0].endswith("/api/amfi/fundperformance")
    ]
    assert performance_calls
    assert all(call["reportDate"] == result["report_date"] for call in performance_calls)
