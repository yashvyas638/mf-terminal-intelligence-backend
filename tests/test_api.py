from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import PortfolioTransactionAudit, Scheme, SessionLocal, init_db
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
    response = client.post(
        f"/v1/portfolios/{portfolio['id']}/transactions/import",
        headers=headers,
        json={"csv_text": csv_text},
    )
    assert response.status_code == 201
    assert response.json()["imported_count"] == 1
    transactions = client.get(f"/v1/portfolios/{portfolio['id']}/transactions", headers=headers).json()
    assert transactions["items"][0]["transaction_type"] == "BUY"