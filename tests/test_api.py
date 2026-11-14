import json
import hashlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

import app.main as main

from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import SQLAlchemyError

from app.db import Portfolio, PortfolioReportSnapshot, BenchmarkIndex, BenchmarkObservation, BenchmarkObservationRevision, FundHolding, FundHoldingDisclosure, FundResearchSnapshot, FundWatchlistItem, IngestionSnapshot, NavObservation, PortfolioTransaction, PortfolioTransactionAudit, PortfolioTransactionIdempotency, PortfolioGoal, Scheme, SchemeBenchmarkAssignment, SessionLocal, init_db
from app.main import app
from app.nav_ingest import parse_amfi_nav_text


@pytest.fixture(autouse=True)
def explicit_operator_test_environment(monkeypatch):
    # Legacy API-key portfolio fixtures are permitted only in an explicit test environment.
    # Individual production-startup tests override this value when needed.
    monkeypatch.setenv("ENVIRONMENT", "test")


class _RoleResult:
    def __init__(self, role):
        self.role = role

    def scalar_one(self):
        return self.role


class _RoleSession:
    def __init__(self, role):
        self.role = role

    def execute(self, statement):
        return _RoleResult(self.role)


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_production_database_role_guard_rejects_supabase_client_roles(role):
    with pytest.raises(RuntimeError, match="trusted server-side PostgreSQL role"):
        main._verify_trusted_database_role(_RoleSession(role))


def test_production_database_role_guard_accepts_server_side_role():
    assert main._verify_trusted_database_role(_RoleSession("service_role")) == "service_role"


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


def test_transaction_idempotency_replays_original_response_and_rejects_payload_reuse(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    init_db()
    scheme_code = 999993
    with SessionLocal() as db:
        if db.get(Scheme, scheme_code) is None:
            db.add(Scheme(
                scheme_code=scheme_code, scheme_name="Idempotency Scheme",
                isin_growth=None, isin_dividend_reinvestment=None,
                first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc),
            ))
            db.commit()
    client = TestClient(app)
    headers = {
        "X-API-Key": "test-api-key-that-is-at-least-32-characters-long",
        "Idempotency-Key": "txn-create-retry-001",
    }
    portfolio = client.post("/v1/portfolios", headers=headers, json={"name": "Idempotency Test"}).json()
    url = f"/v1/portfolios/{portfolio['id']}/transactions"
    payload = {
        "scheme_code": scheme_code, "transaction_type": "BUY",
        "transaction_date": "2026-01-01", "units": "2", "nav": "100", "amount": "200",
    }
    first = client.post(url, headers=headers, json=payload)
    replay = client.post(url, headers=headers, json=payload)
    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == first.json()
    changed = {**payload, "units": "3", "amount": "300"}
    conflict = client.post(url, headers=headers, json=changed)
    assert conflict.status_code == 409
    with SessionLocal() as db:
        transactions = db.execute(
            select(PortfolioTransaction).where(PortfolioTransaction.portfolio_id == portfolio["id"])
        ).scalars().all()
        idempotency = db.execute(
            select(PortfolioTransactionIdempotency).where(
                PortfolioTransactionIdempotency.portfolio_id == portfolio["id"]
            )
        ).scalars().all()
        events = db.execute(
            select(PortfolioTransactionAudit).where(
                PortfolioTransactionAudit.transaction_id == first.json()["id"]
            )
        ).scalars().all()
    assert len(transactions) == 1
    assert len(idempotency) == 1
    assert len(events) == 1


def test_transaction_without_idempotency_key_preserves_existing_client_contract(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    init_db()
    scheme_code = 999994
    with SessionLocal() as db:
        if db.get(Scheme, scheme_code) is None:
            db.add(Scheme(
                scheme_code=scheme_code, scheme_name="Legacy Transaction Scheme",
                isin_growth=None, isin_dividend_reinvestment=None,
                first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc),
            ))
            db.commit()
    client = TestClient(app)
    headers = {"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"}
    portfolio = client.post("/v1/portfolios", headers=headers, json={"name": "Legacy Contract"}).json()
    response = client.post(
        f"/v1/portfolios/{portfolio['id']}/transactions",
        headers=headers,
        json={"scheme_code": scheme_code, "transaction_type": "BUY", "transaction_date": "2026-01-01",
              "units": "1", "nav": "100", "amount": "100"},
    )
    assert response.status_code == 201
    assert "id" in response.json()


def test_portfolio_ledger_rejects_cash_mismatch_and_oversell_and_records_audit(monkeypatch):
    # These fixtures intentionally exercise the legacy operator path outside production.
    monkeypatch.setenv("ENVIRONMENT", "test")
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
    # These fixtures intentionally exercise the legacy operator path outside production.
    monkeypatch.setenv("ENVIRONMENT", "test")
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
    # These fixtures intentionally exercise the legacy operator path outside production.
    monkeypatch.setenv("ENVIRONMENT", "test")
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
    # These fixtures intentionally exercise the legacy operator path outside production.
    monkeypatch.setenv("ENVIRONMENT", "test")
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
    # These fixtures intentionally exercise the legacy operator path outside production.
    monkeypatch.setenv("ENVIRONMENT", "test")
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


def test_stale_nav_is_disclosed_in_valuation_and_blocks_rebalance(monkeypatch):
    # These fixtures intentionally exercise the legacy operator path outside production.
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    init_db()
    now = datetime.now(timezone.utc)
    scheme_code = 999998
    with SessionLocal() as db:
        if db.get(Scheme, scheme_code) is None:
            db.add(Scheme(
                scheme_code=scheme_code,
                scheme_name="Stale NAV Test Fund",
                isin_growth=None,
                isin_dividend_reinvestment=None,
                first_seen_at=now,
                last_seen_at=now,
            ))
        snapshot = IngestionSnapshot(
            source_url="https://example.invalid/nav",
            retrieved_at=now,
            payload_sha256="b" * 64,
            records_valid=1,
            unique_scheme_codes=1,
            min_nav_date=date(2026, 11, 1),
            max_nav_date=date(2026, 11, 1),
            invalid_rows=0,
            duplicate_rows_skipped=0,
            quality_status="PASS",
            report_json="{}",
        )
        db.add(snapshot)
        db.flush()
        db.add(NavObservation(
            scheme_code=scheme_code,
            nav_date=date(2026, 11, 1),
            nav_value="100.00000000",
            source_snapshot_id=snapshot.id,
        ))
        db.commit()

    client = TestClient(app)
    headers = {"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"}
    nav_status = client.get("/v1/nav/status", headers=headers).json()
    assert nav_status["effective_nav_status"] == "STALE_EFFECTIVE_DATE"
    portfolio = client.post("/v1/portfolios", headers=headers, json={"name": "Stale NAV Test"}).json()
    added = client.post(
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
    )
    assert added.status_code == 201
    valuation = client.get(f"/v1/portfolios/{portfolio['id']}/valuation", headers=headers).json()
    assert valuation["valuation_freshness"] == "STALE"
    assert valuation["stale_nav_scheme_codes"] == [scheme_code]
    assert valuation["xirr"] is None
    rebalance = client.post(
        f"/v1/portfolios/{portfolio['id']}/rebalance/preview",
        headers=headers,
        json={"targets": [{"scheme_code": scheme_code, "target_percent": "100"}]},
    )
    assert rebalance.status_code == 409
    assert "stale NAVs" in rebalance.json()["detail"]


def test_scheme_detail_and_fund_comparison_use_persisted_nav_data(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    init_db()
    now = datetime.now(timezone.utc)
    scheme_codes = [999981, 999982]
    with SessionLocal() as db:
        for code, name in zip(scheme_codes, ["Comparison Fund A", "Comparison Fund B"], strict=True):
            if db.get(Scheme, code) is None:
                db.add(Scheme(
                    scheme_code=code,
                    scheme_name=name,
                    isin_growth=None,
                    isin_dividend_reinvestment=None,
                    first_seen_at=now,
                    last_seen_at=now,
                ))
        snapshot = IngestionSnapshot(
            source_url="https://example.invalid/nav",
            retrieved_at=now,
            payload_sha256="b" * 64,
            records_valid=4,
            unique_scheme_codes=2,
            min_nav_date=date(2026, 10, 1),
            max_nav_date=date(2026, 11, 10),
            invalid_rows=0,
            duplicate_rows_skipped=0,
            quality_status="PASS",
            report_json="{}",
        )
        db.add(snapshot)
        db.flush()
        for code, old_nav, new_nav in [(scheme_codes[0], "100", "110"), (scheme_codes[1], "100", "105")]:
            db.add_all([
                NavObservation(scheme_code=code, nav_date=date(2026, 10, 1), nav_value=old_nav, source_snapshot_id=snapshot.id),
                NavObservation(scheme_code=code, nav_date=date(2026, 11, 10), nav_value=new_nav, source_snapshot_id=snapshot.id),
            ])
        db.commit()

    client = TestClient(app)
    headers = {"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"}
    detail = client.get(f"/v1/nav/schemes/{scheme_codes[0]}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["scheme_name"] == "Comparison Fund A"
    assert detail.json()["latest_nav"] == "110.00000000"

    comparison = client.post(
        "/v1/analytics/compare",
        headers=headers,
        json={"scheme_codes": scheme_codes, "days": 365},
    )
    assert comparison.status_code == 200
    results = comparison.json()["results"]
    assert len(results) == 2
    assert results[0]["metrics"]["total_return"] == pytest.approx(0.10)
    assert results[1]["metrics"]["total_return"] == pytest.approx(0.05)


def test_scheme_detail_and_comparison_require_api_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    client = TestClient(app)
    assert client.get("/v1/nav/schemes/999981").status_code == 401
    assert client.post("/v1/analytics/compare", json={"scheme_codes": [1, 2]}).status_code == 401



def test_research_profile_and_screener_use_persisted_nav_and_amfi_plan_metadata(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    init_db()
    now = datetime.now(timezone.utc)
    scheme_code = 999980
    with SessionLocal() as db:
        if db.get(Scheme, scheme_code) is None:
            db.add(Scheme(
                scheme_code=scheme_code,
                scheme_name="Research Profile Test Fund - Direct - Growth",
                isin_growth=None,
                isin_dividend_reinvestment=None,
                first_seen_at=now,
                last_seen_at=now,
                plan_type="Direct",
                option_type="Growth",
                category_group="Equity Scheme",
                category="Large Cap Fund",
                asset_class="Equity",
            ))
        snapshot = IngestionSnapshot(
            source_url="https://example.invalid/nav",
            retrieved_at=now,
            payload_sha256="c" * 64,
            records_valid=400,
            unique_scheme_codes=1,
            min_nav_date=date.today() - timedelta(days=399),
            max_nav_date=date.today(),
            invalid_rows=0,
            duplicate_rows_skipped=0,
            quality_status="PASS",
            report_json="{}",
        )
        db.add(snapshot)
        db.flush()
        db.add_all([
            NavObservation(
                scheme_code=scheme_code,
                nav_date=date.today() - timedelta(days=day),
                nav_value=str(100 + (399 - day) * 0.05),
                source_snapshot_id=snapshot.id,
            )
            for day in range(400)
        ])
        db.commit()

    client = TestClient(app)
    headers = {"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"}
    profile = client.get(f"/v1/analytics/research/{scheme_code}?days=365", headers=headers)
    assert profile.status_code == 200
    result = profile.json()
    assert result["scheme"]["plan_type"] == "Direct"
    assert result["scheme"]["option_type"] == "Growth"
    assert result["metrics"]["status"] == "OK"
    assert "rolling_1y" in result["metrics"]
    assert "data_limitations" in result

    rebuilt = client.post("/v1/analytics/screener/refresh", headers=headers)
    assert rebuilt.status_code == 200, rebuilt.text

    evidence = client.get(
        f"/v1/analytics/research/{scheme_code}/evidence?days=365",
        headers=headers,
    )
    assert evidence.status_code == 200, evidence.text
    evidence_json = evidence.json()
    assert evidence_json["generation_status"] == "EVIDENCE_ONLY_NO_LLM_GENERATION"
    assert any(item["evidence_type"] == "SOURCE_FACT" for item in evidence_json["evidence"])
    assert any(source["source_type"] == "OFFICIAL_NAV_SOURCE" for source in evidence_json["sources"])
    assert evidence_json["data_gaps"]

    screener = client.get(
        "/v1/analytics/screener?category_group=Equity+Scheme&sub_category=Large+Cap+Fund&plan_type=Direct&option_type=Growth&limit=10",
        headers=headers,
    )
    assert screener.status_code == 200
    assert screener.json()["total_matching"] == 1
    assert screener.json()["items"][0]["scheme_code"] == scheme_code
    assert screener.json()["items"][0]["category_group"] == "Equity Scheme"
    assert screener.json()["items"][0]["category"] == "Large Cap Fund"
    assert screener.json()["items"][0]["return_1y"] is not None
    assert client.get("/v1/analytics/screener").status_code == 401



def test_fund_explorer_facets_filters_and_pagination(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    init_db()
    now = datetime.now(timezone.utc)
    fixtures = [
        Scheme(
            scheme_code=999970,
            scheme_name="Explorer Equity Direct Growth",
            amc="Explorer AMC",
            category_group="Equity Scheme",
            category="Flexi Cap Fund",
            asset_class="Equity",
            plan_type="Direct",
            option_type="Growth",
            isin_growth="INF000X01001",
            isin_dividend_reinvestment=None,
            first_seen_at=now,
            last_seen_at=now,
        ),
        Scheme(
            scheme_code=999971,
            scheme_name="Explorer Equity Regular Growth",
            amc="Explorer AMC",
            category_group="Equity Scheme",
            category="Flexi Cap Fund",
            asset_class="Equity",
            plan_type="Regular",
            option_type="Growth",
            isin_growth=None,
            isin_dividend_reinvestment=None,
            first_seen_at=now,
            last_seen_at=now,
        ),
        Scheme(
            scheme_code=999972,
            scheme_name="Explorer Debt Direct Growth",
            amc="Explorer AMC",
            category_group="Debt Scheme",
            category="Short Term Fund",
            asset_class="Debt",
            plan_type="Direct",
            option_type="Growth",
            isin_growth=None,
            isin_dividend_reinvestment=None,
            first_seen_at=now,
            last_seen_at=now,
        ),
        Scheme(
            scheme_code=999973,
            scheme_name="PowerUp Marketing Label Fund",
            amc="Unclassified AMC",
            category_group="Power Select",
            category="PowerUp",
            asset_class="B",
            plan_type="Direct",
            option_type="Growth",
            isin_growth=None,
            isin_dividend_reinvestment=None,
            first_seen_at=now,
            last_seen_at=now,
        ),
        Scheme(
            scheme_code=999974,
            scheme_name="Equity With Invalid Stored Subcategory",
            amc="Explorer AMC",
            category_group="Equity Scheme",
            category="PowerUp",
            asset_class="Equity",
            plan_type="Direct",
            option_type="Growth",
            isin_growth=None,
            isin_dividend_reinvestment=None,
            first_seen_at=now,
            last_seen_at=now,
        ),
        Scheme(
            scheme_code=999975,
            scheme_name="Life Cycle Ten Year Fund",
            amc="Explorer AMC",
            category_group="Life Cycle Funds",
            category="Life Cycle Fund with Maturity of 10 Years",
            asset_class=None,
            plan_type="Direct",
            option_type="Growth",
            isin_growth=None,
            isin_dividend_reinvestment=None,
            first_seen_at=now,
            last_seen_at=now,
        ),
        Scheme(
            scheme_code=999976,
            scheme_name="Legacy Other Scheme FoF",
            amc="Legacy AMC",
            category_group="Other Scheme",
            category="FoF Domestic",
            asset_class="Other",
            plan_type="Direct",
            option_type="Growth",
            isin_growth=None,
            isin_dividend_reinvestment=None,
            first_seen_at=now,
            last_seen_at=now,
        ),
    ]
    with SessionLocal() as db:
        for scheme in fixtures:
            if db.get(Scheme, scheme.scheme_code) is None:
                db.add(scheme)
        db.commit()

    client = TestClient(app)
    headers = {"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"}
    facets = client.get("/v1/nav/facets", headers=headers)
    assert facets.status_code == 200
    assert "Explorer AMC" in facets.json()["amcs"]
    assert "Equity Scheme" in facets.json()["categories"]
    assert "Flexi Cap Fund" in facets.json()["sub_categories"]
    assert "Power Select" not in facets.json()["categories"]
    assert "PowerUp" not in facets.json()["sub_categories"]
    assert "Life Cycle Funds" in facets.json()["categories"]
    assert "Life Cycle" not in facets.json()["asset_classes"]
    assert "Life Cycle Fund with Maturity of 10 Years" in facets.json()["sub_categories"]
    assert "FoFs (Overseas/Domestic)" in facets.json()["sub_categories"]
    assert "B" not in facets.json()["asset_classes"]

    filtered = client.get(
        "/v1/nav/schemes",
        params={"amc": "Explorer AMC", "category_group": "Equity Scheme", "sub_category": "Flexi Cap Fund", "plan_type": "Direct", "limit": 1, "offset": 0},
        headers=headers,
    )
    assert filtered.status_code == 200
    assert filtered.json()["total_matching"] == 1
    assert filtered.json()["items"][0]["scheme_code"] == 999970
    legacy_other = client.get(
        "/v1/nav/schemes",
        params={"category_group": "Other Schemes", "sub_category": "FoFs (Overseas/Domestic)"},
        headers=headers,
    )
    assert legacy_other.status_code == 200
    assert legacy_other.json()["total_matching"] == 1
    assert legacy_other.json()["items"][0]["category_group"] == "Other Schemes"
    assert legacy_other.json()["items"][0]["category"] == "FoFs (Overseas/Domestic)"

    page = client.get(
        "/v1/nav/schemes",
        params={"q": "Explorer", "limit": 2, "offset": 1},
        headers=headers,
    )
    assert page.status_code == 200
    assert page.json()["total_matching"] == 5  # scheme-name and AMC matches, including two additional taxonomy fixtures
    assert len(page.json()["items"]) == 2
    assert len({item["scheme_code"] for item in page.json()["items"]}) == 2
    isin_search = client.get(
        "/v1/nav/schemes",
        params={"q": "INF000X01001"},
        headers=headers,
    )
    assert isin_search.status_code == 200
    assert isin_search.json()["total_matching"] == 1
    assert isin_search.json()["items"][0]["scheme_code"] == 999970

    unclassified = client.get(
        "/v1/nav/schemes",
        params={"q": "999973"},
        headers=headers,
    )
    assert unclassified.status_code == 200
    assert unclassified.json()["items"][0]["category_group"] is None
    assert unclassified.json()["items"][0]["category"] is None
    assert unclassified.json()["items"][0]["asset_class"] is None

    invalid_subcategory = client.get(
        "/v1/nav/schemes",
        params={"q": "999974"},
        headers=headers,
    )
    assert invalid_subcategory.status_code == 200
    assert invalid_subcategory.json()["items"][0]["category_group"] == "Equity Scheme"
    assert invalid_subcategory.json()["items"][0]["category"] is None
    assert invalid_subcategory.json()["items"][0]["asset_class"] == "Equity"


def test_two_authenticated_users_cannot_access_each_others_portfolios(monkeypatch):
    """Exercise the real bearer-auth middleware and owner checks with two identities."""
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    init_db()
    identities = {"token-user-one": "user-one-00000000-0000-000000000001", "token-user-two": "user-two-00000000-0000-000000000002"}

    class AuthResponse:
        status_code = 200

        def __init__(self, user_id):
            self.user_id = user_id

        def json(self):
            return {"id": self.user_id}

    def fake_auth_get(url, headers, timeout):
        assert url.endswith("/auth/v1/user")
        token = headers["Authorization"].removeprefix("Bearer ")
        return AuthResponse(identities[token])

    monkeypatch.setenv("SUPABASE_URL", "https://auth.example.test")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test_key")
    monkeypatch.setattr(main.requests, "get", fake_auth_get)

    client = TestClient(app)
    user_one = {"Authorization": "Bearer token-user-one"}
    user_two = {"Authorization": "Bearer token-user-two"}

    created = client.post("/v1/portfolios", headers=user_one, json={"name": "Private portfolio"})
    assert created.status_code == 201
    portfolio_id = created.json()["id"]

    one_list = client.get("/v1/portfolios", headers=user_one)
    two_list = client.get("/v1/portfolios", headers=user_two)
    assert one_list.status_code == 200
    assert [item["id"] for item in one_list.json()["items"]] == [portfolio_id]
    assert two_list.status_code == 200
    assert two_list.json()["items"] == []

    # Every data-bearing route must conceal another user's portfolio as not found.
    for path in (
        f"/v1/portfolios/{portfolio_id}/transactions",
        f"/v1/portfolios/{portfolio_id}/valuation",
        f"/v1/portfolios/{portfolio_id}/risk",
        f"/v1/portfolios/{portfolio_id}/lookthrough",
        f"/v1/portfolios/{portfolio_id}/tax-lots",
        f"/v1/portfolios/{portfolio_id}/reports",
    ):
        response = client.get(path, headers=user_two)
        assert response.status_code == 404, (path, response.text)

    blocked_write = client.post(
        f"/v1/portfolios/{portfolio_id}/transactions",
        headers=user_two,
        json={
            "scheme_code": 999991,
            "transaction_type": "BUY",
            "transaction_date": "2026-01-01",
            "units": "1",
            "nav": "100",
            "amount": "100",
        },
    )
    assert blocked_write.status_code == 404

    blocked_stress = client.post(
        f"/v1/portfolios/{portfolio_id}/stress",
        headers=user_two,
        json={"scenario_name": "Unauthorized shock", "shocks": [{"scheme_code": 999991, "shock_pct": "-10"}]},
    )
    assert blocked_stress.status_code == 404

    own_empty_transactions = client.get(
        f"/v1/portfolios/{portfolio_id}/transactions", headers=user_one
    )
    assert own_empty_transactions.status_code == 200
    assert own_empty_transactions.json()["count"] == 0

def test_fund_watchlists_are_persistent_and_isolated_between_two_users(monkeypatch):
    """Each account can save/remove the same scheme without seeing another account's list."""
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    monkeypatch.setenv("SUPABASE_URL", "https://auth.example.test")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test_key")
    init_db()
    scheme_code = 999980
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        if db.get(Scheme, scheme_code) is None:
            db.add(Scheme(
                scheme_code=scheme_code,
                scheme_name="Watchlist Isolation Fund",
                isin_growth=None,
                isin_dividend_reinvestment=None,
                first_seen_at=now,
                last_seen_at=now,
                plan_type="Direct",
                option_type="Growth",
            ))
            db.commit()

    identities = {
        "watchlist-user-one": "00000000-0000-0000-0000-000000000011",
        "watchlist-user-two": "00000000-0000-0000-0000-000000000022",
    }

    class AuthResponse:
        status_code = 200

        def __init__(self, user_id):
            self.user_id = user_id

        def json(self):
            return {"id": self.user_id}

    monkeypatch.setattr(
        main.requests,
        "get",
        lambda url, headers, timeout: AuthResponse(
            identities[headers["Authorization"].removeprefix("Bearer ")]
        ),
    )

    client = TestClient(app)
    user_one = {"Authorization": "Bearer watchlist-user-one"}
    user_two = {"Authorization": "Bearer watchlist-user-two"}

    assert client.get("/v1/watchlist").status_code == 401

    added = client.post("/v1/watchlist", headers=user_one, json={"scheme_code": scheme_code})
    assert added.status_code == 201
    duplicate = client.post("/v1/watchlist", headers=user_one, json={"scheme_code": scheme_code})
    assert duplicate.status_code == 409

    assert client.get("/v1/watchlist", headers=user_two).json()["items"] == []
    blocked_remove = client.delete(f"/v1/watchlist/{scheme_code}", headers=user_two)
    assert blocked_remove.status_code == 404
    assert client.get("/v1/watchlist", headers=user_one).json()["count"] == 1

    second_added = client.post("/v1/watchlist", headers=user_two, json={"scheme_code": scheme_code})
    assert second_added.status_code == 201
    assert client.get("/v1/watchlist", headers=user_one).json()["count"] == 1
    assert client.get("/v1/watchlist", headers=user_two).json()["count"] == 1

    removed_one = client.delete(f"/v1/watchlist/{scheme_code}", headers=user_one)
    assert removed_one.status_code == 200
    assert client.get("/v1/watchlist", headers=user_one).json()["count"] == 0
    assert client.get("/v1/watchlist", headers=user_two).json()["count"] == 1

    with SessionLocal() as db:
        rows = db.query(FundWatchlistItem).all()
        assert len(rows) == 1
        assert rows[0].owner_user_id == identities["watchlist-user-two"]

def test_global_fund_screener_ranks_before_pagination_and_enforces_operator_refresh(monkeypatch):
    """Global rank is stable across pages, filters and selected metric order."""
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    monkeypatch.setattr(main, "_research_snapshots_are_current", lambda: True)
    init_db()
    now = datetime.now(timezone.utc)
    as_of = date(2026, 11, 10)
    scheme_codes = (999983, 999984, 99999999, 99999998, 99999997)
    with SessionLocal() as db:
        snapshot = IngestionSnapshot(
            source_url="https://example.test/nav",
            retrieved_at=now,
            payload_sha256="a" * 64,
            records_valid=2,
            unique_scheme_codes=2,
            min_nav_date=as_of - timedelta(days=400),
            max_nav_date=as_of,
            invalid_rows=0,
            duplicate_rows_skipped=0,
            quality_status="PASS",
            report_json="{}",
        )
        db.add(snapshot)
        db.flush()
        source_labels = {
            scheme_codes[0]: ("Direct Plan", "Growth"),
            scheme_codes[1]: ("Direct", "Growth Option"),
            scheme_codes[2]: ("Direct Plan", "GROWTH"),
            scheme_codes[3]: ("Direct Plan", "Growth"),
            scheme_codes[4]: ("Direct Plan", "GROWTH"),
        }
        for code, name in (
            (scheme_codes[0], "Global Rank Alpha"),
            (scheme_codes[1], "Global Rank Beta"),
            (scheme_codes[2], "Global Rank Stale"),
            (scheme_codes[3], "Global Rank Unclassified"),
            (scheme_codes[4], "Global Rank Gamma"),
        ):
            db.add(Scheme(
                scheme_code=code,
                scheme_name=name,
                isin_growth=None,
                isin_dividend_reinvestment=None,
                first_seen_at=now,
                last_seen_at=now,
                category_group=None if code == scheme_codes[3] else "Equity Scheme",
                category=None if code == scheme_codes[3] else "CI Test Category",
                asset_class=None if code == scheme_codes[3] else "Equity",
                plan_type=source_labels[code][0],
                option_type=source_labels[code][1],
            ))
        db.flush()
        nav_rows = []
        for index in range(401):
            nav_date = as_of - timedelta(days=400 - index)
            nav_rows.append(NavObservation(
                scheme_code=scheme_codes[0],
                nav_date=nav_date,
                nav_value=Decimal(str(100 + index * 0.30)),
                source_snapshot_id=snapshot.id,
            ))
            nav_rows.append(NavObservation(
                scheme_code=scheme_codes[1],
                nav_date=nav_date,
                nav_value=Decimal(str(100 + index * 0.10)),
                source_snapshot_id=snapshot.id,
            ))
            stale_nav_date = as_of - timedelta(days=21 + 400 - index)
            nav_rows.append(NavObservation(
                scheme_code=scheme_codes[2],
                nav_date=stale_nav_date,
                nav_value=Decimal(str(100 + index * 0.20)),
                source_snapshot_id=snapshot.id,
            ))
            nav_rows.append(NavObservation(
                scheme_code=scheme_codes[3],
                nav_date=nav_date,
                nav_value=Decimal(str(100 + index * 0.05)),
                source_snapshot_id=snapshot.id,
            ))
            nav_rows.append(NavObservation(
                scheme_code=scheme_codes[4],
                nav_date=nav_date,
                nav_value=Decimal(str(100 + index * 0.08)),
                source_snapshot_id=snapshot.id,
            ))
        db.add_all(nav_rows)
        db.commit()

    client = TestClient(app)
    assert client.post("/v1/analytics/screener/refresh").status_code == 401
    headers = {"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"}
    refreshed = client.post("/v1/analytics/screener/refresh", headers=headers)
    assert refreshed.status_code == 200, refreshed.text
    result = refreshed.json()
    assert result["status"] == "refreshed"
    assert result["schemes_processed"] >= 2
    assert result["snapshot_rows_written"] == result["schemes_processed"] * 4
    with SessionLocal() as db:
        assert db.query(FundResearchSnapshot).filter_by(scheme_code=scheme_codes[2]).count() == 0

    first_page = client.get(
        "/v1/analytics/screener?q=Global+Rank&days=365&sort_by=return_1y&sort_order=desc&limit=1&offset=0",
        headers=headers,
    )
    second_page = client.get(
        "/v1/analytics/screener?q=Global+Rank&days=365&sort_by=return_1y&sort_order=desc&limit=1&offset=1",
        headers=headers,
    )
    assert first_page.status_code == 200, first_page.text
    assert second_page.status_code == 200, second_page.text
    first = first_page.json()
    second = second_page.json()
    assert first["total_matching"] >= 2
    assert first["items"][0]["rank"] == 1
    assert second["items"][0]["rank"] == 2
    assert first["items"][0]["scheme_code"] == scheme_codes[0]
    assert first["items"][0]["return_1y"] > second["items"][0]["return_1y"]
    assert first["items"][0]["category_rank"] == 1
    assert second["items"][0]["category_rank"] == 2
    unclassified = client.get(
        "/v1/analytics/screener?q=Global+Rank+Unclassified&days=365&sort_by=return_1y",
        headers=headers,
    )
    assert unclassified.status_code == 200
    assert unclassified.json()["items"][0]["category_rank"] is None
    assert "before pagination" in first["sorting_note"]

    ascending = client.get(
        "/v1/analytics/screener?q=Global+Rank&days=365&sort_by=return_1y&sort_order=asc&limit=2",
        headers=headers,
    )
    assert ascending.status_code == 200
    assert ascending.json()["items"][0]["scheme_code"] == scheme_codes[3]
    assert ascending.json()["items"][0]["category_rank"] is None

    filtered = client.get(
        "/v1/analytics/screener?days=365&plan_type=Direct+Plan&min_observations=300",
        headers=headers,
    )
    assert filtered.status_code == 200
    assert all(item["observations"] >= 300 for item in filtered.json()["items"])
    one_month = client.get(
        "/v1/analytics/screener?q=Global+Rank&days=30&sort_by=return_1m",
        headers=headers,
    )
    assert one_month.status_code == 200
    assert one_month.json()["items"][0]["scheme_code"] == scheme_codes[0]
    assert one_month.json()["items"][0]["category_rank"] == 1

    insufficient_5y = client.get(
        "/v1/analytics/screener?q=Global+Rank&days=1825&sort_by=return_5y",
        headers=headers,
    )
    assert insufficient_5y.status_code == 200
    assert insufficient_5y.json()["total_matching"] == 0

    invalid_window = client.get("/v1/analytics/screener?days=500", headers=headers)
    assert invalid_window.status_code == 422
    unsupported_10y = client.get("/v1/analytics/screener?days=3650", headers=headers)
    assert unsupported_10y.status_code == 422

    with SessionLocal() as db:
        persisted = db.query(FundResearchSnapshot).filter(
            FundResearchSnapshot.window_days == 365
        ).all()
        assert len(persisted) >= 2
        assert all(item.metrics_json for item in persisted)



def test_nav_ingestion_refreshes_research_snapshots_and_reports_result(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    captured = {}

    def fake_refresh(*, x_api_key):
        captured["key"] = x_api_key
        return {
            "status": "refreshed",
            "schemes_processed": 42,
            "snapshot_rows_written": 168,
            "refreshed_at": "2026-11-12T10:00:00+00:00",
        }

    monkeypatch.setattr(main, "refresh_fund_research_snapshots", fake_refresh)
    result = main._refresh_research_snapshots_after_ingestion()
    assert captured["key"] == "test-api-key-that-is-at-least-32-characters-long"
    assert result["status"] == "refreshed"
    assert result["schemes_processed"] == 42
    assert result["snapshot_rows_written"] == 168


def test_nav_ingestion_remains_successful_when_research_snapshot_refresh_fails(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")

    def failed_refresh(*, x_api_key):
        raise RuntimeError("snapshot build failed")

    monkeypatch.setattr(main, "refresh_fund_research_snapshots", failed_refresh)
    result = main._refresh_research_snapshots_after_ingestion()
    assert result == {"status": "deferred", "error_type": "RuntimeError"}



def test_monthly_category_leaderboard_ranks_calendar_month_and_tracks_rank_movement(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    monkeypatch.setattr(main, "_research_snapshots_are_current", lambda: True)
    init_db()
    now = datetime.now(timezone.utc)
    codes = (999961, 999962, 999963, 999964, 999965, 999966, 999967)
    monthly = {
        codes[0]: [{"month": "2026-09", "return": 0.03}, {"month": "2026-10", "return": 0.04}],
        codes[1]: [{"month": "2026-09", "return": 0.08}, {"month": "2026-10", "return": 0.02}],
        codes[2]: [{"month": "2026-09", "return": 0.02}, {"month": "2026-10", "return": -0.01}],
        codes[3]: [{"month": "2026-09", "return": 0.01}, {"month": "2026-10", "return": 0.03}],
        codes[4]: [{"month": "2026-09", "return": 0.02}, {"month": "2026-10", "return": 0.05}],
        codes[5]: [{"month": "2026-09", "return": 0.90}, {"month": "2026-10", "return": 0.90}],
        codes[6]: [{"month": "2026-09", "return": 0.80}, {"month": "2026-10", "return": 0.95}],
    }
    source_labels = [
        ("Direct Plan", "Growth"),
        ("Direct Plan", "Growth Option"),
        ("Direct Plan", "GROWTH"),
        ("Direct Plan", "IDCW Option"),
        ("Direct Plan", "Monthly IDCW"),
        ("Regular Plan", "Growth Option"),
        ("Direct Plan", "Unclaimed IDCW Less than 3 years"),
    ]
    with SessionLocal() as db:
        for index, code in enumerate(codes):
            if db.get(Scheme, code) is None:
                db.add(Scheme(
                    scheme_code=code,
                    scheme_name=f"Monthly Leaderboard Fund {index}",
                    isin_growth=None,
                    isin_dividend_reinvestment=None,
                    first_seen_at=now,
                    last_seen_at=now,
                    plan_type=source_labels[index][0],
                    option_type=source_labels[index][1],
                    category_group="Equity Scheme",
                    category="Flexi Cap Fund",
                    asset_class="Equity",
                ))
        db.flush()
        for code in codes:
            db.add(FundResearchSnapshot(
                scheme_code=code,
                window_days=365,
                nav_as_of_date=date(2026, 11, 10),
                refreshed_at=now,
                observations=250,
                metrics_json=json.dumps({"monthly_returns": monthly[code]}),
                return_1m=monthly[code][-1]["return"],
                return_1y=0.12,
                return_3y=None,
                cagr=0.10,
                volatility=0.15,
                sharpe_ratio=0.8,
                sortino_ratio=1.0,
                max_drawdown=-0.12,
                positive_month_rate=0.6,
                rolling_1y_positive_rate=0.7,
            ))
        db.commit()

    client = TestClient(app)
    headers = {"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"}
    response = client.get(
        "/v1/analytics/monthly-leaderboard?month=2026-10&category_group=Equity+Scheme&sub_category=Flexi+Cap+Fund&plan_type=Direct&option_type=Growth&limit=3",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["month"] == "2026-10"
    assert result["previous_month"] == "2026-09"
    assert result["count"] == 3
    assert [item["scheme_code"] for item in result["items"]] == [codes[0], codes[1], codes[2]]
    assert [item["category_rank"] for item in result["items"]] == [1, 2, 3]
    assert [item["rank_change"] for item in result["items"]] == [1, -1, 0]
    assert {item["plan_type"] for item in result["items"]} == {"Direct"}
    assert {item["option_type"] for item in result["items"]} == {"Growth"}
    assert "No interpolation" in result["methodology"]

    idcw = client.get(
        "/v1/analytics/monthly-leaderboard?month=2026-10&category_group=Equity+Scheme&sub_category=Flexi+Cap+Fund&plan_type=Direct&option_type=IDCW&limit=3",
        headers=headers,
    )
    assert idcw.status_code == 200, idcw.text
    idcw_result = idcw.json()
    assert idcw_result["count"] == 2
    assert [item["scheme_code"] for item in idcw_result["items"]] == [codes[4], codes[3]]
    assert {item["option_type"] for item in idcw_result["items"]} == {"IDCW"}

    regular = client.get(
        "/v1/analytics/monthly-leaderboard?month=2026-10&category_group=Equity+Scheme&sub_category=Flexi+Cap+Fund&plan_type=Regular&option_type=Growth&limit=3",
        headers=headers,
    )
    assert regular.status_code == 200, regular.text
    regular_result = regular.json()
    assert regular_result["count"] == 1
    assert [item["scheme_code"] for item in regular_result["items"]] == [codes[5]]

    future = client.get(
        "/v1/analytics/monthly-leaderboard?month=2026-12",
        headers=headers,
    )
    assert future.status_code == 422
    invalid = client.get(
        "/v1/analytics/monthly-leaderboard?month=2026-13",
        headers=headers,
    )
    assert invalid.status_code == 422



def test_benchmark_tri_import_correction_provenance_and_verified_scheme_mapping(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    init_db()
    now = datetime.now(timezone.utc)
    scheme_code = 87654321
    with SessionLocal() as db:
        if db.get(Scheme, scheme_code) is None:
            db.add(Scheme(
                scheme_code=scheme_code,
                scheme_name="Benchmark Mapping Test Growth Fund",
                isin_growth=None,
                isin_dividend_reinvestment=None,
                first_seen_at=now,
                last_seen_at=now,
                plan_type="Direct",
                option_type="Growth",
            ))
            db.commit()

    headers = {"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"}
    client = TestClient(app)
    csv_text = (
        "IndexName,Date,Total Returns Index,Net Total Return Index\n"
        "NIFTY 50,01-Jan-2026,25000.00,24950.00\n"
        "NIFTY 50,02-Jan-2026,25100.00,25050.00\n"
        "NIFTY 50,05-Jan-2026,25200.00,25150.00\n"
    )
    payload = {
        "benchmark_code": "NIFTY_50_TRI",
        "benchmark_name": "NIFTY 50",
        "variant": "TRI",
        "csv_text": csv_text,
    }
    assert client.post("/v1/benchmarks/import-csv", json=payload).status_code == 401

    first = client.post("/v1/benchmarks/import-csv", headers=headers, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["inserted_rows"] == 3
    second = client.post("/v1/benchmarks/import-csv", headers=headers, json=payload)
    assert second.status_code == 200, second.text
    assert second.json()["inserted_rows"] == 0
    assert second.json()["unchanged_rows"] == 3

    corrected_csv = csv_text.replace("25100.00", "25110.00")
    corrected = client.post(
        "/v1/benchmarks/import-csv",
        headers=headers,
        json={**payload, "csv_text": corrected_csv},
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["corrected_rows"] == 1

    listed = client.get("/v1/benchmarks", headers=headers)
    assert listed.status_code == 200
    assert any(item["benchmark_code"] == "NIFTY_50_TRI" for item in listed.json()["items"])

    with SessionLocal() as db:
        nav_snapshot = IngestionSnapshot(
            source_url="https://example.test/nav",
            retrieved_at=now,
            payload_sha256="b" * 64,
            records_valid=3,
            unique_scheme_codes=1,
            min_nav_date=date(2026, 1, 1),
            max_nav_date=date(2026, 1, 5),
            invalid_rows=0,
            duplicate_rows_skipped=0,
            quality_status="PASS",
            report_json="{}",
        )
        db.add(nav_snapshot)
        db.flush()
        db.add_all([
            NavObservation(
                scheme_code=scheme_code,
                nav_date=observation_date,
                nav_value=nav_value,
                source_snapshot_id=nav_snapshot.id,
            )
            for observation_date, nav_value in (
                (date(2026, 1, 1), "100.00"),
                (date(2026, 1, 2), "101.00"),
                (date(2026, 1, 5), "103.00"),
            )
        ])
        db.commit()

    assignment_payload = {
        "scheme_code": scheme_code,
        "benchmark_code": "NIFTY_50_TRI",
        "tier": 1,
        "valid_from": "2025-01-01",
        "valid_to": None,
        "source_document_url": "https://www.example-amc.com/factsheet.pdf",
        "source_document_sha256": "a" * 64,
    }
    created = client.post("/v1/benchmarks/assignments", headers=headers, json=assignment_payload)
    assert created.status_code == 201, created.text
    assignment_id = created.json()["assignment_id"]
    assert created.json()["verification_status"] == "PENDING"

    pending_compare = client.get(
        f"/v1/analytics/research/{scheme_code}/benchmark", headers=headers
    )
    assert pending_compare.status_code == 200
    assert pending_compare.json()["status"] == "UNMAPPED"

    verified = client.post(
        f"/v1/benchmarks/assignments/{assignment_id}/verify", headers=headers
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["verification_status"] == "VERIFIED"

    comparison = client.get(
        f"/v1/analytics/research/{scheme_code}/benchmark?days=3650",
        headers=headers,
    )
    assert comparison.status_code == 200, comparison.text
    comparison_json = comparison.json()
    assert comparison_json["status"] == "OK"
    assert len(comparison_json["comparisons"]) == 1
    aligned = comparison_json["comparisons"][0]["metrics"]
    assert aligned["common_observations"] == 3
    assert aligned["fund_total_return"] == pytest.approx(0.03)
    assert aligned["risk_statistics_status"] == "INSUFFICIENT_DAILY_OBSERVATIONS"
    assert aligned["beta"] is None

    with SessionLocal() as db:
        benchmark = db.get(BenchmarkIndex, "NIFTY_50_TRI")
        assert benchmark is not None and benchmark.variant == "TRI"
        assert db.query(BenchmarkObservation).filter_by(benchmark_code="NIFTY_50_TRI").count() == 3
        assert db.query(BenchmarkObservationRevision).filter_by(benchmark_code="NIFTY_50_TRI").count() == 1
        mapping = db.get(SchemeBenchmarkAssignment, assignment_id)
        assert mapping.verification_status == "VERIFIED"
        assert mapping.verified_at is not None

    wrong_variant = client.post(
        "/v1/benchmarks/import-csv",
        headers=headers,
        json={**payload, "variant": "NTR"},
    )
    assert wrong_variant.status_code == 409

def test_holdings_disclosures_are_immutable_and_overlap_uses_common_isins(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    init_db()
    now = datetime.now(timezone.utc)
    scheme_a, scheme_b = 87654322, 87654323
    with SessionLocal() as db:
        for code, name in (
            (scheme_a, "Holdings Overlap Fund A"),
            (scheme_b, "Holdings Overlap Fund B"),
        ):
            if db.get(Scheme, code) is None:
                db.add(Scheme(
                    scheme_code=code,
                    scheme_name=name,
                    isin_growth=None,
                    isin_dividend_reinvestment=None,
                    first_seen_at=now,
                    last_seen_at=now,
                    plan_type="Direct",
                    option_type="Growth",
                ))
        db.commit()

    headers = {"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"}
    client = TestClient(app)
    csv_a = (
        "ISIN,Name of Instrument,% to Net Assets,Asset Type,Sector\n"
        "INE002A01018,Example Bank Ltd,5.25,Equity,Financial Services\n"
        "INE009A01021,Example Technology Ltd,3.50,Equity,Information Technology\n"
        ",Net Current Assets,2.00,Cash,\n"
    )
    csv_b = (
        "ISIN,Name of Instrument,% to Net Assets,Asset Type,Sector\n"
        "INE002A01018,Example Bank Ltd,3.00,Equity,Financial Services\n"
        "INE009A01021,Example Technology Ltd,1.00,Equity,Information Technology\n"
        "INE123A01016,Other Listed Company,5.00,Equity,Industrials\n"
    )

    def import_payload(code, as_of, text):
        return {
            "scheme_code": code,
            "as_of_date": as_of,
            "source_document_url": "https://www.amfiindia.com/portfolio-disclosure/example.csv",
            "source_document_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "csv_text": text,
        }

    imported_a = client.post(
        "/v1/holdings/import-csv",
        headers=headers,
        json=import_payload(scheme_a, "2026-10-31", csv_a),
    )
    imported_b = client.post(
        "/v1/holdings/import-csv",
        headers=headers,
        json=import_payload(scheme_b, "2026-09-30", csv_b),
    )
    assert imported_a.status_code == 200, imported_a.text
    assert imported_b.status_code == 200, imported_b.text
    assert imported_a.json()["status"] == "imported"
    duplicate = client.post(
        "/v1/holdings/import-csv",
        headers=headers,
        json=import_payload(scheme_a, "2026-10-31", csv_a),
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "already_imported"
    assert duplicate.json()["verification_status"] == "PENDING"

    pending_holdings = client.get(f"/v1/holdings/{scheme_a}", headers=headers)
    assert pending_holdings.status_code == 404
    verified_a = client.post(
        f"/v1/holdings/disclosures/{imported_a.json()['disclosure_id']}/verify",
        headers=headers,
    )
    verified_b = client.post(
        f"/v1/holdings/disclosures/{imported_b.json()['disclosure_id']}/verify",
        headers=headers,
    )
    assert verified_a.status_code == 200 and verified_a.json()["verification_status"] == "VERIFIED"
    assert verified_b.status_code == 200 and verified_b.json()["verification_status"] == "VERIFIED"

    overlap = client.get(
        f"/v1/analytics/holdings-overlap?scheme_a={scheme_a}&scheme_b={scheme_b}",
        headers=headers,
    )
    assert overlap.status_code == 200, overlap.text
    result = overlap.json()
    assert result["status"] == "OK"
    assert result["common_isin_count"] == 2
    assert float(result["holdings_overlap_pct"]) == pytest.approx(4.0)
    assert float(result["shared_weight_in_scheme_a_pct"]) == pytest.approx(8.75)
    assert float(result["shared_weight_in_scheme_b_pct"]) == pytest.approx(4.0)
    assert len(result["top_shared_holdings"]) == 2

    holdings = client.get(f"/v1/holdings/{scheme_a}", headers=headers)
    assert holdings.status_code == 200
    assert holdings.json()["row_count"] == 3
    assert any(not item["is_isin"] for item in holdings.json()["items"])

    corrected_csv = csv_a.replace("5.25", "5.50")
    correction = client.post(
        "/v1/holdings/import-csv",
        headers=headers,
        json=import_payload(scheme_a, "2026-10-31", corrected_csv),
    )
    assert correction.status_code == 200, correction.text
    assert correction.json()["supersedes_disclosure_id"] == imported_a.json()["disclosure_id"]

    with SessionLocal() as db:
        assert db.query(FundHoldingDisclosure).filter_by(scheme_code=scheme_a).count() == 2
        assert db.query(FundHolding).count() == 9

def test_portfolio_historical_risk_and_user_defined_stress(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    monkeypatch.setenv("SUPABASE_URL", "https://auth.example.test")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test_key")
    init_db()
    user_id = "00000000-0000-0000-0000-000000000044"

    class AuthResponse:
        status_code = 200

        def json(self):
            return {"id": user_id}

    monkeypatch.setattr(main.requests, "get", lambda url, headers, timeout: AuthResponse())
    client = TestClient(app)
    headers = {"Authorization": "Bearer portfolio-risk-user"}

    created = client.post("/v1/portfolios", headers=headers, json={"name": "Risk Test Portfolio"})
    assert created.status_code == 201, created.text
    portfolio_id = created.json()["id"]
    scheme_code = 87654324
    now = datetime.now(timezone.utc)
    as_of = date(2026, 11, 10)

    with SessionLocal() as db:
        db.add(Scheme(
            scheme_code=scheme_code,
            scheme_name="Portfolio Risk Growth Fund",
            isin_growth=None,
            isin_dividend_reinvestment=None,
            first_seen_at=now,
            last_seen_at=now,
            plan_type="Direct",
            option_type="Growth",
        ))
        snapshot = IngestionSnapshot(
            source_url="https://example.test/nav",
            retrieved_at=now,
            payload_sha256="c" * 64,
            records_valid=100,
            unique_scheme_codes=1,
            min_nav_date=as_of - timedelta(days=99),
            max_nav_date=as_of,
            invalid_rows=0,
            duplicate_rows_skipped=0,
            quality_status="PASS",
            report_json="{}",
        )
        db.add(snapshot)
        db.flush()
        disclosure = FundHoldingDisclosure(
            scheme_code=scheme_code,
            as_of_date=as_of,
            source_document_url="https://example.test/verified-holdings.csv",
            source_sha256="e" * 64,
            retrieved_at=now,
            row_count=1,
            total_weight_pct=Decimal("100"),
            verification_status="VERIFIED",
            verified_at=now,
            supersedes_disclosure_id=None,
        )
        db.add(disclosure)
        db.flush()
        db.add(FundHolding(
            disclosure_id=disclosure.id,
            security_id="INE123A01016",
            security_name="Example Financial Services Ltd",
            is_isin=True,
            asset_type="Equity",
            sector="Financial Services",
            weight_pct=Decimal("100"),
            market_value_inr=None,
        ))
        db.add(PortfolioTransaction(
            portfolio_id=portfolio_id,
            scheme_code=scheme_code,
            transaction_type="BUY",
            transaction_date=as_of - timedelta(days=90),
            units=Decimal("10"),
            nav=Decimal("100"),
            amount=Decimal("1000"),
            charges=Decimal("0"),
            notes="Risk test seed",
            created_at=now,
            voided_at=None,
            void_reason=None,
        ))
        db.add_all([
            PortfolioTransaction(
                portfolio_id=portfolio_id,
                scheme_code=scheme_code,
                transaction_type="BUY",
                transaction_date=as_of - timedelta(days=60),
                units=Decimal("5"),
                nav=Decimal("110"),
                amount=Decimal("550"),
                charges=Decimal("0"),
                notes="Second FIFO lot",
                created_at=now,
                voided_at=None,
                void_reason=None,
            ),
            PortfolioTransaction(
                portfolio_id=portfolio_id,
                scheme_code=scheme_code,
                transaction_type="SELL",
                transaction_date=as_of - timedelta(days=30),
                units=Decimal("6"),
                nav=Decimal("120"),
                amount=Decimal("720"),
                charges=Decimal("0"),
                notes="FIFO redemption",
                created_at=now,
                voided_at=None,
                void_reason=None,
            ),
        ])
        nav_rows = []
        value = 100.0
        for index in range(100):
            observed_date = as_of - timedelta(days=99 - index)
            daily_return = 0.001 if index % 8 else -0.015
            value *= 1 + daily_return
            nav_rows.append(NavObservation(
                scheme_code=scheme_code,
                nav_date=observed_date,
                nav_value=Decimal(str(round(value, 8))),
                source_snapshot_id=snapshot.id,
            ))
        db.add_all(nav_rows)
        db.commit()

    tax_lots = client.get(f"/v1/portfolios/{portfolio_id}/tax-lots", headers=headers)
    assert tax_lots.status_code == 200, tax_lots.text
    tax_json = tax_lots.json()
    assert tax_json["realized_lot_count"] == 1
    assert tax_json["open_lot_count"] == 2
    assert tax_json["realized_gain_loss"] == "120.00"
    assert tax_json["tax_status"] == "TAX_RULES_NOT_APPLIED"
    assert len(tax_json["open_lots"]) == 2

    lookthrough = client.get(f"/v1/portfolios/{portfolio_id}/lookthrough", headers=headers)
    assert lookthrough.status_code == 200, lookthrough.text
    look_json = lookthrough.json()
    assert look_json["coverage"]["status"] == "COMPLETE"
    assert look_json["coverage"]["covered_weight_pct"] == pytest.approx(100.0)
    assert look_json["top_securities"][0]["security_id"] == "INE123A01016"
    assert look_json["top_securities"][0]["identity_basis"] == "ISIN"
    assert look_json["top_securities"][0]["fresh_disclosure_exposure_inr"] == look_json["top_securities"][0]["lookthrough_value"]
    assert look_json["top_securities"][0]["stale_disclosure_exposure_inr"] == "0.00"
    concentration = look_json["security_concentration"]
    assert concentration["basis"] == "OBSERVED_VERIFIED_DISCLOSURES_ONLY"
    assert concentration["top_1_weight_of_observed_positive_pct"] == "100.0000"
    assert concentration["top_5_weight_of_observed_positive_pct"] == "100.0000"
    assert concentration["hhi_points"] == "10000.00"
    assert concentration["effective_security_count"] == "1.0000"
    assert concentration["isin_identity_coverage_pct"] == "100.0000"
    assert concentration["fresh_positive_disclosed_exposure_inr"] == look_json["top_securities"][0]["lookthrough_value"]
    assert concentration["stale_positive_disclosed_exposure_inr"] == "0.00"
    assert look_json["sector_exposure"][0]["sector"] == "Financial Services"

    risk = client.get(f"/v1/portfolios/{portfolio_id}/risk?days=365", headers=headers)
    assert risk.status_code == 200, risk.text
    risk_json = risk.json()
    assert risk_json["status"] == "OK"
    assert risk_json["holdings_count"] == 1
    assert risk_json["metrics"]["daily_return_observations"] >= 30
    assert risk_json["metrics"]["annualized_volatility"] > 0
    assert risk_json["metrics"]["historical_var_95"] > 0
    assert risk_json["metrics"]["max_drawdown"] < 0

    stress = client.post(
        f"/v1/portfolios/{portfolio_id}/stress",
        headers=headers,
        json={
            "scenario_name": "Broad 10 percent drawdown",
            "shocks": [{"scheme_code": scheme_code, "shock_pct": "-10"}],
        },
    )
    assert stress.status_code == 200, stress.text
    stress_json = stress.json()
    assert stress_json["scenario_type"] == "USER_DEFINED_SENSITIVITY_NOT_FORECAST"
    assert float(stress_json["estimated_portfolio_impact"]) == pytest.approx(
        round(-float(stress_json["base_portfolio_value"]) * 0.10, 2),
        abs=0.01,
    )
    assert float(stress_json["stressed_portfolio_value"]) == pytest.approx(
        round(float(stress_json["base_portfolio_value"]) * 0.90, 2),
        abs=0.01,
    )

    saved_report = client.post(
        f"/v1/portfolios/{portfolio_id}/reports?days=365",
        headers=headers,
    )
    assert saved_report.status_code == 201, saved_report.text
    report_id = saved_report.json()["report_id"]
    report_list = client.get(f"/v1/portfolios/{portfolio_id}/reports", headers=headers)
    assert report_list.status_code == 200
    assert report_list.json()["count"] == 1
    report_detail = client.get(f"/v1/reports/{report_id}", headers=headers)
    assert report_detail.status_code == 200
    assert report_detail.json()["report"]["report_version"] == "portfolio-report-v1"
    assert report_detail.json()["report"]["lookthrough"]["coverage"]["status"] == "COMPLETE"
    assert report_detail.json()["content_sha256"] == saved_report.json()["content_sha256"]
    assert report_detail.json()["integrity_status"] == "VERIFIED"
    pdf = client.get(f"/v1/reports/{report_id}/pdf", headers=headers)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    with SessionLocal() as db:
        assert db.query(PortfolioReportSnapshot).filter_by(id=report_id).count() == 1

    incomplete = client.post(
        f"/v1/portfolios/{portfolio_id}/stress",
        headers=headers,
        json={"scenario_name": "Missing shock", "shocks": []},
    )
    assert incomplete.status_code == 422

def test_financial_goals_are_private_and_projection_is_owner_scoped(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    monkeypatch.setenv("SUPABASE_URL", "https://auth.example.test")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test_key")
    init_db()
    identities = {
        "goal-user-one": "00000000-0000-0000-0000-000000000055",
        "goal-user-two": "00000000-0000-0000-0000-000000000066",
    }

    class AuthResponse:
        status_code = 200

        def __init__(self, user_id):
            self.user_id = user_id

        def json(self):
            return {"id": self.user_id}

    monkeypatch.setattr(
        main.requests,
        "get",
        lambda url, headers, timeout: AuthResponse(
            identities[headers["Authorization"].removeprefix("Bearer ")]
        ),
    )
    client = TestClient(app)
    user_one = {"Authorization": "Bearer goal-user-one"}
    user_two = {"Authorization": "Bearer goal-user-two"}
    payload = {
        "name": "Long-term wealth goal",
        "target_amount_today": "10000000",
        "target_date": "2036-01-01",
        "current_amount": "500000",
        "monthly_contribution": "25000",
        "inflation_rate": 0.06,
        "annual_return_low": 0.04,
        "annual_return_base": 0.10,
        "annual_return_high": 0.14,
    }

    created = client.post("/v1/goals", headers=user_one, json=payload)
    assert created.status_code == 201, created.text
    goal_id = created.json()["id"]

    one_list = client.get("/v1/goals", headers=user_one)
    two_list = client.get("/v1/goals", headers=user_two)
    assert one_list.status_code == 200
    assert len(one_list.json()["items"]) == 1
    assert two_list.status_code == 200
    assert two_list.json()["items"] == []

    owner_portfolio = client.post(
        "/v1/portfolios",
        headers=user_one,
        json={"name": "Private linked goal portfolio"},
    )
    assert owner_portfolio.status_code == 201, owner_portfolio.text
    cross_owner_link = client.post(
        "/v1/goals",
        headers=user_two,
        json={**payload, "linked_portfolio_id": owner_portfolio.json()["id"]},
    )
    assert cross_owner_link.status_code == 404

    scheme_code = 87654325
    now = datetime.now(timezone.utc)
    nav_date = date.today()
    with SessionLocal() as db:
        db.add(Scheme(
            scheme_code=scheme_code,
            scheme_name="Linked Goal Test Fund",
            isin_growth=None,
            isin_dividend_reinvestment=None,
            first_seen_at=now,
            last_seen_at=now,
            plan_type="Direct",
            option_type="Growth",
        ))
        snapshot = IngestionSnapshot(
            source_url="https://example.test/goal-nav",
            retrieved_at=now,
            payload_sha256="d" * 64,
            records_valid=1,
            unique_scheme_codes=1,
            min_nav_date=nav_date,
            max_nav_date=nav_date,
            invalid_rows=0,
            duplicate_rows_skipped=0,
            quality_status="PASS",
            report_json="{}",
        )
        db.add(snapshot)
        db.flush()
        db.add(PortfolioTransaction(
            portfolio_id=owner_portfolio.json()["id"],
            scheme_code=scheme_code,
            transaction_type="BUY",
            transaction_date=nav_date,
            units=Decimal("10"),
            nav=Decimal("100"),
            amount=Decimal("1000"),
            charges=Decimal("0"),
            notes="Goal link test",
            created_at=now,
            voided_at=None,
            void_reason=None,
        ))
        db.add(NavObservation(
            scheme_code=scheme_code,
            nav_date=nav_date,
            nav_value=Decimal("100"),
            source_snapshot_id=snapshot.id,
        ))
        db.commit()

    linked_payload = {**payload, "linked_portfolio_id": owner_portfolio.json()["id"]}
    linked_update = client.put(f"/v1/goals/{goal_id}", headers=user_one, json=linked_payload)
    assert linked_update.status_code == 200, linked_update.text
    linked_projection = client.get(f"/v1/goals/{goal_id}/projection", headers=user_one)
    assert linked_projection.status_code == 200, linked_projection.text
    assert linked_projection.json()["current_amount_source"] == "LINKED_PORTFOLIO_MARKET_VALUE"
    assert linked_projection.json()["linked_portfolio"]["portfolio_id"] == owner_portfolio.json()["id"]
    assert linked_projection.json()["projection"]["current_amount"] == 1000.0
    unlinked = client.put(f"/v1/goals/{goal_id}", headers=user_one, json=payload)
    assert unlinked.status_code == 200

    projection = client.get(f"/v1/goals/{goal_id}/projection", headers=user_one)
    assert projection.status_code == 200, projection.text
    assert projection.json()["projection"]["inflation_adjusted_target"] > 10_000_000
    assert projection.json()["current_amount_source"] == "USER_ENTERED"
    assert projection.json()["linked_portfolio"] is None
    assert set(projection.json()["projection"]["scenarios"]) == {"low", "base", "high"}

    assert client.get(f"/v1/goals/{goal_id}/projection", headers=user_two).status_code == 404
    assert client.put(f"/v1/goals/{goal_id}", headers=user_two, json=payload).status_code == 404
    assert client.delete(f"/v1/goals/{goal_id}", headers=user_two).status_code == 404

    updated_payload = {**payload, "monthly_contribution": "30000"}
    updated = client.put(f"/v1/goals/{goal_id}", headers=user_one, json=updated_payload)
    assert updated.status_code == 200
    assert client.get("/v1/goals", headers=user_one).json()["items"][0]["monthly_contribution"] == "30000.00"
    assert client.delete(f"/v1/goals/{goal_id}", headers=user_one).status_code == 200

    with SessionLocal() as db:
        assert db.query(PortfolioGoal).filter_by(owner_user_id=identities["goal-user-one"]).count() == 0


def test_nav_snapshot_persists_official_amc_and_category_metadata():
    init_db()
    payload = """Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
Test Asset Management Mutual Fund
Open Ended Schemes(Equity Scheme - Large Cap Fund)
999965;INF000A01001;-;Power Select Test Fund;10.1234;21-Oct-2026
"""
    records, report = parse_amfi_nav_text(payload)
    main._persist_nav_snapshot(records, report, datetime.now(timezone.utc))
    with SessionLocal() as db:
        scheme = db.get(Scheme, 999965)
        assert scheme is not None
        assert scheme.amc == "Test Asset Management Mutual Fund"
        assert scheme.structure == "Open Ended"
        assert scheme.category_group == "Equity Scheme"
        assert scheme.category == "Large Cap Fund"
        assert scheme.asset_class == "Equity"



def test_production_portfolio_owner_guard_rejects_operator_key_without_user(monkeypatch):
    """A valid shared operator key must not become a wildcard for private portfolios."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    init_db()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        portfolio = Portfolio(
            owner_user_id="00000000-0000-0000-0000-000000000001",
            name="Private production portfolio",
            currency="INR",
            created_at=now,
        )
        db.add(portfolio)
        db.commit()
        db.refresh(portfolio)
        portfolio_id = portfolio.id

        token = main._authenticated_user_id.set(None)
        try:
            with pytest.raises(main.HTTPException) as exc:
                main._require_portfolio_owner(db, portfolio_id)
            assert exc.value.status_code == 401
        finally:
            main._authenticated_user_id.reset(token)

        token = main._authenticated_user_id.set("00000000-0000-0000-0000-000000000002")
        try:
            with pytest.raises(main.HTTPException) as exc:
                main._require_portfolio_owner(db, portfolio_id)
            assert exc.value.status_code == 404
        finally:
            main._authenticated_user_id.reset(token)



def test_production_operator_api_key_cannot_read_or_mutate_personal_portfolios(monkeypatch):
    """The operator key remains useful for operations, never as a personal-data identity."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    init_db()
    with SessionLocal() as db:
        portfolio = Portfolio(
            owner_user_id="00000000-0000-0000-0000-000000000003",
            name="Private account",
            currency="INR",
            created_at=datetime.now(timezone.utc),
        )
        db.add(portfolio)
        db.commit()
        db.refresh(portfolio)
        portfolio_id = portfolio.id

    client = TestClient(app)
    operator = {"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"}
    assert client.get("/v1/portfolios", headers=operator).status_code == 401
    assert client.post("/v1/portfolios", headers=operator, json={"name": "Operator portfolio"}).status_code == 401
    assert client.get(
        f"/v1/portfolios/{portfolio_id}/transactions", headers=operator
    ).status_code == 401
    assert client.post(
        f"/v1/portfolios/{portfolio_id}/transactions",
        headers=operator,
        json={
            "scheme_code": 999991,
            "transaction_type": "BUY",
            "transaction_date": "2026-01-01",
            "units": "1",
            "nav": "100",
            "amount": "100",
        },
    ).status_code == 401



def test_history_worker_schedules_snapshot_refresh_after_worker_returns(monkeypatch):
    """The bounded history worker must not run the expensive snapshot rebuild inline."""
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_RUN_ON_START", "true")
    monkeypatch.setenv("AMFI_HISTORY_CONTRACT_VERIFIED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_ENABLED", "true")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_BATCH_LIMIT", "1")
    monkeypatch.setenv("AMFI_HISTORY_BACKFILL_MAX_WINDOWS_PER_START", "1")
    monkeypatch.setenv("AMFI_HISTORY_PLAN_MODE", "daily")

    monkeypatch.setattr(
        main,
        "run_history_backfill_batch",
        lambda **kwargs: {
            "status": "idle",
            "selected": 0,
            "completed": 0,
            "failed": 0,
            "results": [],
        },
    )
    monkeypatch.setattr(
        main,
        "_maybe_refresh_research_after_history_completion",
        lambda: pytest.fail("snapshot rebuild must run only after the worker completion callback"),
    )

    result = main._maybe_run_historical_backfill_batch_from_environment()

    assert result["status"] == "idle"
    assert result["research_snapshot_refresh"] == {
        "status": "scheduled",
        "reason": "after_history_worker_completion",
    }



def test_research_snapshot_refresh_skips_when_another_postgres_instance_holds_lock(
    monkeypatch,
):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    with SessionLocal() as lock_holder:
        if lock_holder.get_bind().dialect.name != "postgresql":
            pytest.skip("Cross-instance advisory lock is PostgreSQL-specific")
        lock_holder.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": main.RESEARCH_SNAPSHOT_LOCK_KEY},
        )
        result = main.refresh_fund_research_snapshots(
            x_api_key="test-api-key-that-is-at-least-32-characters-long"
        )
        assert result == {
            "status": "in_progress",
            "reason": "another_instance_refreshing",
        }


def test_refresh_wrapper_preserves_cross_instance_in_progress_status(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    monkeypatch.setattr(
        main,
        "refresh_fund_research_snapshots",
        lambda **kwargs: {
            "status": "in_progress",
            "reason": "another_instance_refreshing",
        },
    )
    result = main._refresh_research_snapshots_after_ingestion()
    assert result == {
        "status": "in_progress",
        "reason": "another_instance_refreshing",
    }


def test_transaction_audit_checks_portfolio_ownership_before_transaction_lookup(monkeypatch):
    """A private portfolio's transaction IDs must not be enumerable by another user."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    init_db()

    def reject_owner(_db, _portfolio_id):
        raise main.HTTPException(status_code=401, detail="personal session required")

    monkeypatch.setattr(main, "_require_portfolio_owner", reject_owner)
    client = TestClient(app)
    response = client.get(
        "/v1/portfolios/987654321/transactions/987654321/audit",
        headers={"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "personal session required"
