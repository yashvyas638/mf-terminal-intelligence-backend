from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

import app.main as main
from app.db import NavObservation, NavObservationRevision, SessionLocal, engine, init_db


def _amfi_response(nav: str):
    body = (
        "Scheme Code;ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date\n"
        f"998877;INF000000001;INF000000002;Correction Test Fund;{nav};10-Nov-2026\n"
    )
    return SimpleNamespace(content=body.encode("utf-8"), raise_for_status=lambda: None)


def test_nav_correction_is_audited_and_replay_is_idempotent(monkeypatch):
    init_db()
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    monkeypatch.setattr(main, "MINIMUM_VALID_RECORDS", 1)
    responses = iter([_amfi_response("100.0000"), _amfi_response("101.0000"), _amfi_response("101.0000")])
    monkeypatch.setattr(main.requests, "get", lambda *args, **kwargs: next(responses))
    client = TestClient(main.app)
    headers = {"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"}

    first = client.post("/v1/nav/refresh", headers=headers)
    second = client.post("/v1/nav/refresh", headers=headers)
    third = client.post("/v1/nav/refresh", headers=headers)

    assert first.status_code == second.status_code == third.status_code == 200
    with SessionLocal() as db:
        current = db.execute(
            select(NavObservation).where(
                NavObservation.scheme_code == 998877,
                NavObservation.nav_date == date(2026, 11, 10),
            )
        ).scalar_one()
        revisions = db.execute(
            select(NavObservationRevision).where(
                NavObservationRevision.scheme_code == 998877,
                NavObservationRevision.nav_date == date(2026, 11, 10),
            )
        ).scalars().all()

    assert Decimal(current.nav_value) == Decimal("101.0000")
    assert len(revisions) == 1
    assert Decimal(revisions[0].previous_nav_value) == Decimal("100.0000")
    assert Decimal(revisions[0].replacement_nav_value) == Decimal("101.0000")


def test_oversized_amfi_payload_is_rejected_before_parsing(monkeypatch):
    init_db()
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    monkeypatch.setattr(main.requests, "get", lambda *args, **kwargs: SimpleNamespace(
        content=b"x" * 30_000_001, raise_for_status=lambda: None
    ))
    response = TestClient(main.app).post(
        "/v1/nav/refresh",
        headers={"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"},
    )
    assert response.status_code == 502
    assert "30 MB" in response.json()["detail"]


def test_invalid_utf8_amfi_payload_is_rejected(monkeypatch):
    init_db()
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    monkeypatch.setattr(main.requests, "get", lambda *args, **kwargs: SimpleNamespace(
        content=b"\xff\xfe", raise_for_status=lambda: None
    ))
    response = TestClient(main.app).post(
        "/v1/nav/refresh",
        headers={"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"},
    )
    assert response.status_code == 502
    assert "valid UTF-8" in response.json()["detail"]


def test_stale_nav_effective_date_is_rejected(monkeypatch):
    init_db()
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    monkeypatch.setattr(main, "MINIMUM_VALID_RECORDS", 1)
    monkeypatch.setattr(main, "MAX_NAV_STALENESS_DAYS", 7)
    stale = (
        "Scheme Code;ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date\n"
        "998876;INF000000003;INF000000004;Stale Test Fund;100.0000;01-Nov-2026\n"
    )
    monkeypatch.setattr(main.requests, "get", lambda *args, **kwargs: SimpleNamespace(
        content=stale.encode("utf-8"), raise_for_status=lambda: None
    ))
    response = TestClient(main.app).post(
        "/v1/nav/refresh",
        headers={"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"},
    )
    assert response.status_code == 502
    assert "stale" in response.json()["detail"]


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostgreSQL advisory lock integration test")
def test_refresh_returns_conflict_when_another_session_holds_distributed_lock(monkeypatch):
    init_db()
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    with SessionLocal() as lock_session:
        acquired = lock_session.execute(
            __import__("sqlalchemy").text("SELECT pg_try_advisory_lock(:lock_key)"),
            {"lock_key": main.NAV_REFRESH_LOCK_KEY},
        ).scalar_one()
        assert acquired is True
        response = TestClient(main.app).post(
            "/v1/nav/refresh",
            headers={"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"},
        )
        assert response.status_code == 409
        lock_session.execute(
            __import__("sqlalchemy").text("SELECT pg_advisory_unlock(:lock_key)"),
            {"lock_key": main.NAV_REFRESH_LOCK_KEY},
        )
