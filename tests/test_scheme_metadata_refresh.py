import pytest

from app import main


def test_scheme_metadata_refresh_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AMFI_SCHEME_METADATA_REFRESH_ON_START", raising=False)
    monkeypatch.delenv("AMFI_SCHEME_METADATA_REFRESH_ENABLED", raising=False)
    assert main._maybe_refresh_scheme_metadata_from_environment() is None


def test_scheme_metadata_refresh_requires_separate_execution_gate(monkeypatch):
    monkeypatch.setenv("AMFI_SCHEME_METADATA_REFRESH_ON_START", "true")
    monkeypatch.setenv("AMFI_SCHEME_METADATA_REFRESH_ENABLED", "false")
    monkeypatch.setenv("AMFI_SCHEME_METADATA_CONTRACT_VERIFIED", "true")
    with pytest.raises(RuntimeError, match="REFRESH_ENABLED"):
        main._maybe_refresh_scheme_metadata_from_environment()


def test_scheme_metadata_refresh_requires_source_contract_gate(monkeypatch):
    monkeypatch.setenv("AMFI_SCHEME_METADATA_REFRESH_ON_START", "true")
    monkeypatch.setenv("AMFI_SCHEME_METADATA_REFRESH_ENABLED", "true")
    monkeypatch.setenv("AMFI_SCHEME_METADATA_CONTRACT_VERIFIED", "false")
    with pytest.raises(RuntimeError, match="CONTRACT_VERIFIED"):
        main._maybe_refresh_scheme_metadata_from_environment()


def test_scheme_metadata_refresh_parses_and_persists_metadata_only(monkeypatch):
    payload = (
        "Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;"
        "Scheme Name;Net Asset Value;Date\n"
        "HDFC Mutual Fund\n"
        "Open Ended Schemes(Equity Scheme - Large Cap Fund)\n"
        "120586;INF109K01480;-;HDFC Large Cap Fund - Direct Plan - Growth;"
        "123.4567;11-Nov-2026\n"
    ).encode("utf-8")
    monkeypatch.setattr(
        main,
        "_fetch_amfi_payload",
        lambda: (payload, {"http_status": 200, "bytes_received": len(payload)}),
    )
    monkeypatch.setattr(main, "MINIMUM_VALID_RECORDS", 1)
    captured = {}

    def fake_persist(records, now):
        captured["records"] = records
        return {
            "scheme_records_seen": 1,
            "scheme_rows_created": 0,
            "scheme_rows_updated": 1,
            "category_metadata_seen": 1,
            "category_group_populated": 1,
            "category_unclassified": 0,
            "plan_type_populated": 0,
            "option_type_populated": 0,
            "amc_populated": 1,
        }

    monkeypatch.setattr(main, "refresh_scheme_metadata", fake_persist)
    result = main._refresh_scheme_metadata_from_amfi()

    assert result["status"] == "refreshed"
    assert result["nav_observations_written"] == 0
    assert result["scheme_rows_updated"] == 1
    assert captured["records"][0].category_group == "Equity Scheme"
    assert captured["records"][0].category == "Large Cap Fund"
    assert captured["records"][0].metadata_present is True


def test_scheme_metadata_refresh_rejects_stale_feed_without_writing(monkeypatch):
    payload = (
        "Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;"
        "Scheme Name;Net Asset Value;Date\n"
        "HDFC Mutual Fund\n"
        "Open Ended Schemes(Equity Scheme - Large Cap Fund)\n"
        "120586;INF109K01480;-;HDFC Large Cap Fund;123.4567;01-Jan-2020\n"
    ).encode("utf-8")
    monkeypatch.setattr(
        main,
        "_fetch_amfi_payload",
        lambda: (payload, {"http_status": 200, "bytes_received": len(payload)}),
    )
    monkeypatch.setattr(main, "MINIMUM_VALID_RECORDS", 1)
    monkeypatch.setattr(main, "MAX_NAV_STALENESS_DAYS", 7)
    monkeypatch.setattr(
        main,
        "refresh_scheme_metadata",
        lambda *args, **kwargs: pytest.fail("stale metadata must not be persisted"),
    )
    with pytest.raises(RuntimeError, match="stale"):
        main._refresh_scheme_metadata_from_amfi()
