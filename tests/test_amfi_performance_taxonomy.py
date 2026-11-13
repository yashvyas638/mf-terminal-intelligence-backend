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


@pytest.mark.parametrize(
    ("source_label", "canonical"),
    [
        ("Large Cap", "Large Cap Fund"),
        ("Large & Mid Cap", "Large & Mid Cap Fund"),
        ("Flexi Cap", "Flexi Cap Fund"),
        ("Multi Cap", "Multi Cap Fund"),
        ("Mid Cap", "Mid Cap Fund"),
        ("Small Cap", "Small Cap Fund"),
        ("Value", "Value Fund"),
        ("ELSS", "ELSS Tax Saver Fund"),
        ("Contra", "Contra Fund"),
        ("Dividend Yield", "Dividend Yield Fund"),
        ("Focused", "Focused Fund (No. of Stocks)"),
        ("Sectoral", "Sectoral Fund"),
        ("Thematic", "Thematic Fund"),
    ],
)
def test_amfi_short_category_labels_map_to_current_sebi_allowlist(source_label, canonical):
    from app.fund_taxonomy import canonical_subcategory

    assert canonical_subcategory("Equity Scheme", source_label) == canonical


@pytest.mark.parametrize(
    ("group", "source_label", "canonical"),
    [
        ("Debt Scheme", "Long Term", "Long Term Fund"),
        ("Debt Scheme", "Medium to Long Term", "Medium to Long Term Fund"),
        ("Debt Scheme", "Short Term", "Short Term Fund"),
        ("Debt Scheme", "Medium Term", "Medium Term Fund"),
        ("Debt Scheme", "Ultra Short to Short Term", "Ultra Short to Short Term Fund"),
        ("Debt Scheme", "Ultra Short Term", "Ultra Short Term Fund"),
        ("Debt Scheme", "Liquid", "Liquid Fund"),
        ("Debt Scheme", "Overnight", "Overnight Fund"),
        ("Debt Scheme", "Dynamic Term", "Dynamic Term Fund"),
        ("Debt Scheme", "Corporate Bond", "Corporate Bond Fund"),
        ("Debt Scheme", "Credit Risk", "Credit Risk Fund"),
        ("Debt Scheme", "Banking and PSU Debt", "Banking and PSU Debt Fund"),
        ("Debt Scheme", "Floating Interest Rates", "Floating Interest Rates Fund"),
        ("Debt Scheme", "Gilt", "Gilt Fund"),
        ("Debt Scheme", "Sectoral Debt Fund", "Sectoral Fund"),
        ("Hybrid Scheme", "Aggressive Hybrid", "Aggressive Hybrid Fund"),
        ("Hybrid Scheme", "Conservative Hyrbid", "Conservative Hybrid Fund"),
        ("Hybrid Scheme", "Balanced Hybrid", "Balanced Hybrid Fund"),
        ("Hybrid Scheme", "Arbitrage", "Arbitrage Fund"),
        ("Other Schemes", "Index Funds ETFs", "Index Funds / ETFs"),
    ],
)
def test_amfi_short_debt_hybrid_and_other_labels_map_to_current_sebi_allowlist(group, source_label, canonical):
    from app.fund_taxonomy import canonical_subcategory

    assert canonical_subcategory(group, source_label) == canonical


def test_canonicalizes_amfi_performance_scheme_name_when_source_has_no_scheme_code():
    mappings, rejected = canonicalize_performance_rows(
        [{"schemeName": "Aditya Birla Sun Life Large Cap Fund"}],
        category_group="Equity Scheme",
        subcategory="Large Cap",
    )
    assert mappings == {
        "name:aditya birla sun life large cap fund": {
            "category_group": "Equity Scheme",
            "category": "Large Cap Fund",
        }
    }
    assert rejected == 0


def test_canonicalizes_amfi_performance_base_scheme_name():
    from app.amfi_performance_taxonomy import canonical_scheme_name

    assert canonical_scheme_name("Aditya Birla Sun Life Large Cap Fund") == (
        "aditya birla sun life large cap fund"
    )
    assert canonical_scheme_name(
        "Aditya Birla Sun Life Large Cap Fund - Direct Plan - Growth"
    ) == "aditya birla sun life large cap fund"
    assert canonical_scheme_name(
        "Aditya Birla Sun Life Large Cap Fund - Regular Plan - IDCW"
    ) == "aditya birla sun life large cap fund"


def test_amfi_combined_sectoral_thematic_category_is_preserved_without_guessing():
    from app.fund_taxonomy import canonical_subcategory

    assert canonical_subcategory("Equity Scheme", "Sectoral / Thematic") == (
        "Sectoral/Thematic Fund"
    )
    assert canonical_subcategory("Equity Scheme", "Sectoral") == "Sectoral Fund"
    assert canonical_subcategory("Equity Scheme", "Thematic") == "Thematic Fund"


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
    assert all(call["reportDate"] == result["report_dates"][0] for call in performance_calls)



def test_taxonomy_refresh_maps_exact_amfi_base_name_to_all_active_plan_variants():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    base_name = "Aditya Birla Sun Life Large Cap Fund"
    try:
        with factory.begin() as db:
            snapshot = IngestionSnapshot(
                source_url="https://portal.amfiindia.com/spages/NAVAll.txt",
                retrieved_at=now,
                payload_sha256="c" * 64,
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
                    scheme_code=119561,
                    scheme_name=base_name + " - Direct Plan - Growth",
                    first_seen_at=now,
                    last_seen_at=now,
                    plan_type="Direct Plan",
                    option_type="Growth",
                ),
                Scheme(
                    scheme_code=119562,
                    scheme_name=base_name + " - Regular Plan - IDCW",
                    first_seen_at=now,
                    last_seen_at=now,
                    plan_type="Regular Plan",
                    option_type="IDCW",
                ),
            ])
            db.flush()
            db.add_all([
                NavObservation(
                    scheme_code=119561,
                    nav_date=date.today(),
                    nav_value="10.0",
                    source_snapshot_id=snapshot.id,
                ),
                NavObservation(
                    scheme_code=119562,
                    nav_date=date.today(),
                    nav_value="11.0",
                    source_snapshot_id=snapshot.id,
                ),
            ])

        result = refresh_scheme_taxonomy(
            {
                "name:aditya birla sun life large cap fund": {
                    "category_group": "Equity Scheme",
                    "category": "Large Cap Fund",
                },
            },
            now,
            session_factory=factory,
        )
        with factory() as db:
            direct = db.get(Scheme, 119561)
            regular = db.get(Scheme, 119562)
            assert direct.category == "Large Cap Fund"
            assert regular.category == "Large Cap Fund"
            assert direct.category_group == "Equity Scheme"
            assert regular.category_group == "Equity Scheme"
        assert result["category_rows_updated"] == 2
        assert result["source_names_unmatched"] == 0
    finally:
        engine.dispose()


def test_taxonomy_refresh_supports_official_life_cycle_group_without_asset_class():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    try:
        with factory.begin() as db:
            snapshot = IngestionSnapshot(
                source_url="https://portal.amfiindia.com/spages/NAVAll.txt",
                retrieved_at=now,
                payload_sha256="d" * 64,
                records_valid=1,
                unique_scheme_codes=1,
                min_nav_date=date.today(),
                max_nav_date=date.today(),
                invalid_rows=0,
                duplicate_rows_skipped=0,
                quality_status="PASS",
                report_json="{}",
            )
            db.add(snapshot)
            db.flush()
            db.add(Scheme(
                scheme_code=119563,
                scheme_name="UTI Life Cycle Fund with Maturity of 10 Years - Direct Plan - Growth",
                first_seen_at=now,
                last_seen_at=now,
                plan_type="Direct Plan",
                option_type="Growth",
            ))
            db.flush()
            db.add(NavObservation(
                scheme_code=119563,
                nav_date=date.today(),
                nav_value="10.0",
                source_snapshot_id=snapshot.id,
            ))

        result = refresh_scheme_taxonomy(
            {
                "name:uti life cycle fund with maturity of 10 years": {
                    "category_group": "Life Cycle Funds",
                    "category": "Life Cycle Fund with Maturity of 10 Years",
                    "asset_class": None,
                },
            },
            now,
            session_factory=factory,
        )
        with factory() as db:
            scheme = db.get(Scheme, 119563)
            assert scheme.category_group == "Life Cycle Funds"
            assert scheme.category == "Life Cycle Fund with Maturity of 10 Years"
            assert scheme.asset_class is None
        assert result["category_rows_updated"] == 1
    finally:
        engine.dispose()
