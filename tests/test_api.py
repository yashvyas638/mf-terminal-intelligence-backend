from datetime import date, datetime, timezone

import pytest

import app.main as main

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from app.db import IngestionSnapshot, NavObservation, PortfolioTransaction, PortfolioTransactionAudit, Scheme, SessionLocal, init_db
from app.main import app


def test_protected_endpoints_fail_closed_when_key_is_missing(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    client = TestClient(app)
    response = client.get("/v1/nav/status")
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_invalid_key_is_rejected(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    client = TestClient(app)
    response = client.get("/v1/nav/status", headers={"X-API-Key": "wrong-secret"})
    assert response.status_code == 401


def test_portfolio_ledger_rejects_cash_mismatch_and_oversell_and_records_audit(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    init_db()
    scheme_code = 999991
    with SessionLocal() as db:
        if db.get(Scheme, scheme_code) is None:
            db.add(
                Scheme(
                    scheme_code=scheme_code,
                    scheme_name="Test Scheme",
                    isin_growth=None,
                    isin_dividend_reinvestment=None,
                    first_seen_at=datetime.now(timezone.utc),
                    last_seen_at=datetime.now(timezone.utc),
                )
            )
            db.commit()

    client = TestClient(app)
    headers = {"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"}
    portfolio = client.post("/v1/portfolios", headers=headers, json={"name": "Integrity Test"}).json()
    invalid_amount = client.post(
        f"/v1/portfolios/{portfolio['id']}/transactions",
        headers=headers,
        json={"scheme_code": scheme_code, "transaction_type": "BUY", "transaction_date": "2026-01-01", "units": "2", "nav": "100", "amount": "201"},
    )
    assert invalid_amount.status_code == 422
    buy = client.post(
        f"/v1/portfolios/{portfolio['id']}/transactions",
        headers=headers,
        json={"scheme_code": scheme_code, "transaction_type": "BUY", "transaction_date": "2026-01-01", "units": "2", "nav": "100", "amount": "200"},
    )
    assert buy.status_code == 201
    same_day_sell = client.post(
        f"/v1/portfolios/{portfolio['id']}/transactions",
        headers=headers,
        json={"scheme_code": scheme_code, "transaction_type": "SELL", "transaction_date": "2026-01-01", "units": "1", "nav": "100", "amount": "100"},
    )
    assert same_day_sell.status_code == 201
    invalid_sell_charges = client.post(
        f"/v1/portfolios/{portfolio['id']}/transactions",
        headers=headers,
        json={"scheme_code": scheme_code, "transaction_type": "SELL", "transaction_date": "2026-01-02", "units": "1", "nav": "100", "amount": "100", "charges": "100"},
    )
    assert invalid_sell_charges.status_code == 422
    oversell = client.post(
        f"/v1/portfolios/{portfolio['id']}/transactions",
        headers=headers,
        json={"scheme_code": scheme_code, "transaction_type": "SELL", "transaction_date": "2026-01-02", "units": "3", "nav": "100", "amount": "300"},
    )
    assert oversell.status_code == 409
    audit_response = client.get(
        f"/v1/portfolios/{portfolio['id']}/transactions/{buy.json()['id']}/audit",
        headers=headers,
    )
    assert audit_response.status_code == 200
    assert audit_response.json()["items"][0]["event_type"] == "CREATED"
    with SessionLocal() as db:
        events = db.execute(select(PortfolioTransactionAudit).where(PortfolioTransactionAudit.transaction_id == buy.json()["id"])).scalars().all()
    assert [event.event_type for event in events] == ["CREATED"]
    with SessionLocal() as db:
        with pytest.raises(SQLAlchemyError):
            db.execute(
                update(PortfolioTransactionAudit)
                .where(PortfolioTransactionAudit.transaction_id == buy.json()["id"])
                .values(details_json="{}")
            )
            db.commit()
        db.rollback()
        with pytest.raises(SQLAlchemyError):
            db.execute(
                update(PortfolioTransaction)
                .where(PortfolioTransaction.id == buy.json()["id"])
                .values(units=3)
            )
            db.commit()
        db.rollback()
        with pytest.raises(SQLAlchemyError):
            db.delete(db.get(PortfolioTransaction, buy.json()["id"]))
            db.commit()
        db.rollback()


def test_statement_import_is_atomic_and_does_not_store_raw_csv(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    init_db()
    scheme_code = 999992
    with SessionLocal() as db:
        if db.get(Scheme, scheme_code) is None:
            db.add(
                Scheme(
                    scheme_code=scheme_code,
                    scheme_name="Imported Scheme",
                    isin_growth=None,
                    isin_dividend_reinvestment=None,
                    first_seen_at=datetime.now(timezone.utc),
                    last_seen_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
    client = TestClient(app)
    headers = {"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"}
    portfolio = client.post("/v1/portfolios", headers=headers, json={"name": "Import Test"}).json()
    csv_text = "date,scheme_code,type,units,nav,amount\n2026-01-01,999992,BUY,2,100,200\n"
    premature = client.post(
        f"/v1/portfolios/{portfolio['id']}/transactions/import",
        headers=headers,
        json={"csv_text": csv_text},
    )
    assert premature.status_code == 428

    preview = client.post(
        f"/v1/portfolios/{portfolio['id']}/transactions/import/preview",
        headers=headers,
        json={"csv_text": csv_text},
    )
    assert preview.status_code == 200
    assert preview.json()["status"] == "PREVIEW_READY"
    assert preview.json()["row_count"] == 1
    before_confirmation = client.get(
        f"/v1/portfolios/{portfolio['id']}/transactions",
        headers=headers,
    )
    assert before_confirmation.json()["count"] == 0

    tampered = client.post(
        f"/v1/portfolios/{portfolio['id']}/transactions/import",
        headers=headers,
        json={"csv_text": csv_text, "confirmation_token": preview.json()["confirmation_token"] + "x"},
    )
    assert tampered.status_code == 428

    response = client.post(
        f"/v1/portfolios/{portfolio['id']}/transactions/import",
        headers=headers,
        json={"csv_text": csv_text, "confirmation_token": preview.json()["confirmation_token"]},
    )
    assert response.status_code == 201
    assert response.json()["imported_count"] == 1

    duplicate = client.post(
        f"/v1/portfolios/{portfolio['id']}/transactions/import",
        headers=headers,
        json={
            "csv_text": "type,date,amount,nav,units,scheme_code\nBUY,2026-01-01,200.00,100.0,2.0,999992\n",
            "confirmation_token": preview.json()["confirmation_token"],
        },
    )
    assert duplicate.status_code == 409
    assert "already been imported" in duplicate.json()["detail"]["message"]

    transactions = client.get(f"/v1/portfolios/{portfolio['id']}/transactions", headers=headers).json()
    assert len(transactions["items"]) == 1
    assert transactions["items"][0]["transaction_type"] == "BUY"

def test_weak_server_api_key_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv("API_KEY", "short-secret")
    client = TestClient(app)
    response = client.get("/v1/nav/status", headers={"X-API-Key": "short-secret"})
    assert response.status_code == 503
    assert "at least 32 characters" in response.json()["detail"]


def test_production_startup_fails_fast_when_api_key_is_missing(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="Production API_KEY"):
        with TestClient(app):
            pass


def test_portfolio_valuation_uses_average_cost_and_decimal_arithmetic(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    init_db()
    scheme_code = 999993
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        if db.get(Scheme, scheme_code) is None:
            db.add(Scheme(
                scheme_code=scheme_code,
                scheme_name="Valuation Test Fund",
                isin_growth=None,
                isin_dividend_reinvestment=None,
                first_seen_at=now,
                last_seen_at=now,
            ))
        snapshot = IngestionSnapshot(
            source_url="https://example.invalid/nav",
            retrieved_at=now,
            payload_sha256="a" * 64,
            records_valid=1,
            unique_scheme_codes=1,
            min_nav_date=date(2026, 11, 10),
            max_nav_date=date(2026, 11, 10),
            invalid_rows=0,
            duplicate_rows_skipped=0,
            quality_status="PASS",
            report_json="{}",
        )
        db.add(snapshot)
        db.flush()
        db.add(NavObservation(
            scheme_code=scheme_code,
            nav_date=date(2026, 11, 10),
            nav_value="140.00000000",
            source_snapshot_id=snapshot.id,
        ))
        db.commit()

    client = TestClient(app)
    headers = {"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"}
    portfolio = client.post("/v1/portfolios", headers=headers, json={"name": "Valuation Test"}).json()
    for tx_date, tx_type, units, nav, amount in [
        ("2026-01-01", "BUY", "10", "100", "1000"),
        ("2026-02-01", "BUY", "10", "120", "1200"),
        ("2026-03-01", "SELL", "5", "130", "650"),
    ]:
        response = client.post(
            f"/v1/portfolios/{portfolio['id']}/transactions",
            headers=headers,
            json={
                "scheme_code": scheme_code,
                "transaction_type": tx_type,
                "transaction_date": tx_date,
                "units": units,
                "nav": nav,
                "amount": amount,
            },
        )
        assert response.status_code == 201

    valuation = client.get(f"/v1/portfolios/{portfolio['id']}/valuation", headers=headers)
    assert valuation.status_code == 200
    result = valuation.json()
    assert result["holdings"][0]["units"] == 15
    assert result["holdings"][0]["cost_basis"] == 1650
    assert result["current_value"] == 2100
    assert result["realized_gain_loss"] == 100
    assert result["unrealized_gain_loss"] == 450
    assert result["total_gain_loss"] == 550


def test_portfolio_rejects_blank_names_and_future_transactions(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    init_db()
    client = TestClient(app)
    headers = {"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"}
    blank = client.post("/v1/portfolios", headers=headers, json={"name": "   "})
    assert blank.status_code == 422

    now = datetime.now(timezone.utc)
    scheme_code = 999995
    with SessionLocal() as db:
        if db.get(Scheme, scheme_code) is None:
            db.add(Scheme(
                scheme_code=scheme_code,
                scheme_name="Future Date Test Fund",
                isin_growth=None,
                isin_dividend_reinvestment=None,
                first_seen_at=now,
                last_seen_at=now,
            ))
            db.commit()
    portfolio = client.post("/v1/portfolios", headers=headers, json={"name": "Date Test"}).json()
    future = client.post(
        f"/v1/portfolios/{portfolio['id']}/transactions",
        headers=headers,
        json={
            "scheme_code": scheme_code,
            "transaction_type": "BUY",
            "transaction_date": "2099-01-01",
            "units": "1",
            "nav": "100",
            "amount": "100",
        },
    )
    assert future.status_code == 422


def test_health_reports_service_identity_and_database_readiness():
    init_db()
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "mf-terminal-intelligence-backend"
    assert response.json()["database"] == "reachable"


def test_transaction_can_be_voided_once_with_audited_reason(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    init_db()
    now = datetime.now(timezone.utc)
    scheme_code = 999996
    with SessionLocal() as db:
        if db.get(Scheme, scheme_code) is None:
            db.add(Scheme(
                scheme_code=scheme_code,
                scheme_name="Void Test Fund",
                isin_growth=None,
                isin_dividend_reinvestment=None,
                first_seen_at=now,
                last_seen_at=now,
            ))
            db.commit()
    client = TestClient(app)
    headers = {"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"}
    portfolio = client.post("/v1/portfolios", headers=headers, json={"name": "Void Test"}).json()
    transaction = client.post(
        f"/v1/portfolios/{portfolio['id']}/transactions",
        headers=headers,
        json={
            "scheme_code": scheme_code,
            "transaction_type": "BUY",
            "transaction_date": "2026-01-01",
            "units": "2",
            "nav": "100",
            "amount": "200",
        },
    ).json()
    invalid_void = client.post(
        f"/v1/portfolios/{portfolio['id']}/transactions/{transaction['id']}/void",
        headers=headers,
        json={"reason": "   "},
    )
    assert invalid_void.status_code == 422
    voided = client.post(
        f"/v1/portfolios/{portfolio['id']}/transactions/{transaction['id']}/void",
        headers=headers,
        json={"reason": "Duplicate statement entry"},
    )
    assert voided.status_code == 200
    audit = client.get(
        f"/v1/portfolios/{portfolio['id']}/transactions/{transaction['id']}/audit",
        headers=headers,
    ).json()
    assert [item["event_type"] for item in audit["items"]] == ["CREATED", "VOIDED"]
    second_void = client.post(
        f"/v1/portfolios/{portfolio['id']}/transactions/{transaction['id']}/void",
        headers=headers,
        json={"reason": "Second attempt"},
    )
    assert second_void.status_code == 409


def test_statement_fingerprint_preserves_same_day_row_order():
    buy_first = main._statement_transactions(
        "date,scheme_code,type,units,nav,amount\n"
        "2026-01-01,999997,BUY,2,100,200\n"
        "2026-01-01,999997,SELL,1,100,100\n"
    )
    sell_first = main._statement_transactions(
        "date,scheme_code,type,units,nav,amount\n"
        "2026-01-01,999997,SELL,1,100,100\n"
        "2026-01-01,999997,BUY,2,100,200\n"
    )
    assert main._canonical_statement_fingerprint(buy_first) != main._canonical_statement_fingerprint(sell_first)
