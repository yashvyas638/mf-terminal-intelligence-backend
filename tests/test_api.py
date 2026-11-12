import hashlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

import app.main as main

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from app.db import PortfolioReportSnapshot, BenchmarkIndex, BenchmarkObservation, BenchmarkObservationRevision, FundHolding, FundHoldingDisclosure, FundResearchSnapshot, FundWatchlistItem, IngestionSnapshot, NavObservation, PortfolioTransaction, PortfolioTransactionAudit, PortfolioGoal, Scheme, SchemeBenchmarkAssignment, SessionLocal, init_db
from app.main import app


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


def test_stale_nav_is_disclosed_in_valuation_and_blocks_rebalance(monkeypatch):
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
        "/v1/analytics/screener?plan_type=Direct&option_type=Growth&limit=10",
        headers=headers,
    )
    assert screener.status_code == 200
    assert screener.json()["total_matching"] == 1
    assert screener.json()["items"][0]["scheme_code"] == scheme_code
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
            category="Flexi Cap",
            asset_class="Equity",
            plan_type="Direct",
            option_type="Growth",
            isin_growth=None,
            isin_dividend_reinvestment=None,
            first_seen_at=now,
            last_seen_at=now,
        ),
        Scheme(
            scheme_code=999971,
            scheme_name="Explorer Equity Regular Growth",
            amc="Explorer AMC",
            category="Flexi Cap",
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
            category="Short Duration",
            asset_class="Debt",
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
    assert "Flexi Cap" in facets.json()["categories"]

    filtered = client.get(
        "/v1/nav/schemes",
        params={"amc": "Explorer AMC", "category": "Flexi Cap", "plan_type": "Direct", "limit": 1, "offset": 0},
        headers=headers,
    )
    assert filtered.status_code == 200
    assert filtered.json()["total_matching"] == 1
    assert filtered.json()["items"][0]["scheme_code"] == 999970

    page = client.get(
        "/v1/nav/schemes",
        params={"q": "Explorer", "limit": 2, "offset": 1},
        headers=headers,
    )
    assert page.status_code == 200
    assert page.json()["total_matching"] == 3
    assert len(page.json()["items"]) == 2
    assert len({item["scheme_code"] for item in page.json()["items"]}) == 2


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
    init_db()
    now = datetime.now(timezone.utc)
    as_of = date(2026, 11, 10)
    scheme_codes = (999983, 999984)
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
        for code, name in ((scheme_codes[0], "Global Rank Alpha"), (scheme_codes[1], "Global Rank Beta")):
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
    assert "before pagination" in first["sorting_note"]

    ascending = client.get(
        "/v1/analytics/screener?q=Global+Rank&days=365&sort_by=return_1y&sort_order=asc&limit=2",
        headers=headers,
    )
    assert ascending.status_code == 200
    assert ascending.json()["items"][0]["scheme_code"] == scheme_codes[1]

    filtered = client.get(
        "/v1/analytics/screener?days=365&plan_type=Direct&min_observations=300",
        headers=headers,
    )
    assert filtered.status_code == 200
    assert all(item["observations"] >= 300 for item in filtered.json()["items"])
    invalid_window = client.get("/v1/analytics/screener?days=500", headers=headers)
    assert invalid_window.status_code == 422

    with SessionLocal() as db:
        persisted = db.query(FundResearchSnapshot).filter(
            FundResearchSnapshot.window_days == 365
        ).all()
        assert len(persisted) >= 2
        assert all(item.metrics_json for item in persisted)

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
