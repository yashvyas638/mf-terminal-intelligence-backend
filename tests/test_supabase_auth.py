from datetime import date, datetime, timedelta, timezone
import hashlib
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

import app.main as main
from app.db import FundWatchlistItem, PortfolioReportSnapshot, Scheme, SessionLocal, init_db


def test_supabase_users_get_isolated_portfolios(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test_key")
    init_db()

    user_a = str(uuid4())
    user_b = str(uuid4())

    def verify_user(url, headers, timeout):
        token = headers["Authorization"].removeprefix("Bearer ")
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"id": user_a if token == "user-a-token" else user_b},
        )

    monkeypatch.setattr(main.requests, "get", verify_user)
    client = TestClient(main.app)

    # Give the watchlist isolation test one known public scheme fixture.
    scheme_code = 99877001
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.query(FundWatchlistItem).filter(
            FundWatchlistItem.scheme_code == scheme_code
        ).delete(synchronize_session=False)
        db.query(Scheme).filter(Scheme.scheme_code == scheme_code).delete(
            synchronize_session=False
        )
        db.add(Scheme(
            scheme_code=scheme_code,
            scheme_name="Auth Isolation Test Scheme",
            isin_growth=None,
            isin_dividend_reinvestment=None,
            first_seen_at=now,
            last_seen_at=now,
            category_group="Equity Scheme",
            category="Flexi Cap Fund",
            asset_class="Equity",
            plan_type="Direct Plan",
            option_type="Growth Option",
        ))
        db.commit()

    assert client.get("/v1/nav/status").status_code == 401

    user_a_headers = {"Authorization": "Bearer user-a-token"}
    user_b_headers = {"Authorization": "Bearer user-b-token"}

    created = client.post(
        "/v1/portfolios",
        headers=user_a_headers,
        json={"name": "Yash Personal", "currency": "INR"},
    )
    assert created.status_code == 201
    portfolio_id = created.json()["id"]

    # A valid shared operator key must not become a wildcard owner when ENVIRONMENT is unset.
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    operator_headers = {"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"}
    assert client.get(
        f"/v1/portfolios/{portfolio_id}/valuation",
        headers=operator_headers,
    ).status_code == 401
    assert client.get("/v1/portfolios", headers=operator_headers).status_code == 401

    transaction_payload = {
        "scheme_code": scheme_code,
        "transaction_type": "BUY",
        "transaction_date": date.today().isoformat(),
        "units": "1",
        "nav": "10",
        "amount": "10",
        "charges": "0",
    }
    own_transaction = client.post(
        f"/v1/portfolios/{portfolio_id}/transactions",
        headers=user_a_headers,
        json=transaction_payload,
    )
    assert own_transaction.status_code == 201
    transaction_id = own_transaction.json()["id"]

    # Cross-account write, import preview, stress and ledger actions must be denied.
    assert client.post(
        f"/v1/portfolios/{portfolio_id}/transactions",
        headers=user_b_headers,
        json=transaction_payload,
    ).status_code == 404
    csv_text = (
        "date,scheme_code,type,units,nav,amount\n"
        + f"{date.today().isoformat()},{scheme_code},BUY,1,10,10"
    )
    assert client.post(
        f"/v1/portfolios/{portfolio_id}/transactions/import/preview",
        headers=user_b_headers,
        json={"csv_text": csv_text},
    ).status_code == 404
    assert client.post(
        f"/v1/portfolios/{portfolio_id}/stress",
        headers=user_b_headers,
        json={"scenario_name": "cross-account attempt", "shocks": [{"scheme_code": scheme_code, "shock_pct": "-10"}]},
    ).status_code == 404
    assert client.post(
        f"/v1/portfolios/{portfolio_id}/transactions/{transaction_id}/void",
        headers=user_b_headers,
        json={"reason": "cross-account void attempt"},
    ).status_code == 404
    assert client.get(
        f"/v1/portfolios/{portfolio_id}/transactions/{transaction_id}/audit",
        headers=user_b_headers,
    ).status_code == 404

    # A different authenticated user cannot generate a report for this portfolio.
    denied_report_create = client.post(
        f"/v1/portfolios/{portfolio_id}/reports",
        headers=user_b_headers,
    )
    assert denied_report_create.status_code == 404

    report_payload = '{"report_version":"portfolio-report-v1","summary":{"current_value":12345}}'
    with SessionLocal() as db:
        report_snapshot = PortfolioReportSnapshot(
            portfolio_id=portfolio_id,
            owner_user_id=user_a,
            generated_at=datetime.now(timezone.utc),
            report_version="portfolio-report-v1",
            content_json=report_payload,
            content_sha256=hashlib.sha256(report_payload.encode("utf-8")).hexdigest(),
            source_max_nav_date=date.today(),
        )
        db.add(report_snapshot)
        db.commit()
        report_id = report_snapshot.id

    assert client.get(
        f"/v1/portfolios/{portfolio_id}/reports",
        headers=user_a_headers,
    ).json()["count"] == 1
    assert client.get(
        f"/v1/portfolios/{portfolio_id}/reports",
        headers=user_b_headers,
    ).status_code == 404
    own_report = client.get(f"/v1/reports/{report_id}", headers=user_a_headers)
    assert own_report.status_code == 200
    assert own_report.json()["integrity_status"] == "VERIFIED"
    assert client.get(f"/v1/reports/{report_id}", headers=user_b_headers).status_code == 404
    assert client.get(f"/v1/reports/{report_id}/pdf", headers=user_a_headers).status_code == 200
    assert client.get(f"/v1/reports/{report_id}/pdf", headers=user_b_headers).status_code == 404

    assert client.get("/v1/portfolios", headers=user_a_headers).json()["count"] == 1
    assert client.get("/v1/portfolios", headers=user_b_headers).json()["count"] == 0

    hidden = client.get(f"/v1/portfolios/{portfolio_id}/valuation", headers=user_b_headers)
    assert hidden.status_code == 404

    hidden_transactions = client.get(
        f"/v1/portfolios/{portfolio_id}/transactions",
        headers=user_b_headers,
    )
    assert hidden_transactions.status_code == 404

    hidden_rebalance = client.post(
        f"/v1/portfolios/{portfolio_id}/rebalance/preview",
        headers=user_b_headers,
        json={"targets": [{"scheme_code": 999999, "target_percent": "100"}]},
    )
    assert hidden_rebalance.status_code == 404

    own_valuation = client.get(
        f"/v1/portfolios/{portfolio_id}/valuation",
        headers=user_a_headers,
    )
    assert own_valuation.status_code == 200

    # Watchlist rows are scoped by verified user identity, even for the same scheme.
    added_by_a = client.post(
        "/v1/watchlist",
        headers=user_a_headers,
        json={"scheme_code": scheme_code},
    )
    assert added_by_a.status_code == 201
    assert client.get("/v1/watchlist", headers=user_a_headers).json()["count"] == 1
    assert client.get("/v1/watchlist", headers=user_b_headers).json()["count"] == 0
    assert client.delete(
        f"/v1/watchlist/{scheme_code}",
        headers=user_b_headers,
    ).status_code == 404

    added_by_b = client.post(
        "/v1/watchlist",
        headers=user_b_headers,
        json={"scheme_code": scheme_code},
    )
    assert added_by_b.status_code == 201
    assert client.get("/v1/watchlist", headers=user_a_headers).json()["count"] == 1
    assert client.get("/v1/watchlist", headers=user_b_headers).json()["count"] == 1

    # Private financial goals must never appear in, or be mutable by, another account.
    goal_payload = {
        "name": "User A Retirement Goal",
        "target_amount_today": "1000000",
        "target_date": (date.today() + timedelta(days=365)).isoformat(),
        "current_amount": "100000",
        "monthly_contribution": "10000",
        "inflation_rate": 0.06,
        "annual_return_low": 0.04,
        "annual_return_base": 0.10,
        "annual_return_high": 0.14,
    }
    created_goal = client.post("/v1/goals", headers=user_a_headers, json=goal_payload)
    assert created_goal.status_code == 201
    goal_id = created_goal.json()["id"]
    assert client.get("/v1/goals", headers=user_a_headers).json()["count"] == 1
    assert client.get("/v1/goals", headers=user_b_headers).json()["count"] == 0
    assert client.get(
        f"/v1/goals/{goal_id}/projection",
        headers=user_b_headers,
    ).status_code == 404
    assert client.put(
        f"/v1/goals/{goal_id}",
        headers=user_b_headers,
        json={**goal_payload, "name": "Attempted cross-account edit"},
    ).status_code == 404
    assert client.delete(
        f"/v1/goals/{goal_id}",
        headers=user_b_headers,
    ).status_code == 404
    assert client.get(
        f"/v1/goals/{goal_id}/projection",
        headers=user_a_headers,
    ).status_code == 200


def test_invalid_supabase_session_is_rejected(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test_key")
    monkeypatch.setattr(
        main.requests,
        "get",
        lambda *args, **kwargs: SimpleNamespace(status_code=401, json=lambda: {}),
    )
    response = TestClient(main.app).get(
        "/v1/nav/status",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == 401


def test_supabase_session_revocation_is_checked_on_every_request(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test_key")
    init_db()
    active = {"value": True}
    user_id = str(uuid4())

    def verify_user(url, headers, timeout):
        if not active["value"]:
            return SimpleNamespace(status_code=401, json=lambda: {})
        return SimpleNamespace(status_code=200, json=lambda: {"id": user_id})

    monkeypatch.setattr(main.requests, "get", verify_user)
    client = TestClient(main.app)
    headers = {"Authorization": "Bearer revocable-session-token"}

    first = client.get("/v1/portfolios", headers=headers)
    assert first.status_code == 200
    assert first.json()["count"] == 0

    # Simulate server-side session revocation between two otherwise identical requests.
    active["value"] = False
    revoked = client.get("/v1/portfolios", headers=headers)
    assert revoked.status_code == 401
    assert "expired" in revoked.json()["detail"].lower()


def test_supabase_auth_verification_outage_fails_closed(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test_key")

    def unavailable(*args, **kwargs):
        raise main.requests.Timeout("synthetic auth provider timeout")

    monkeypatch.setattr(main.requests, "get", unavailable)
    response = TestClient(main.app).get(
        "/v1/portfolios",
        headers={"Authorization": "Bearer valid-looking-but-unverified-token"},
    )
    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"].lower()


def test_supabase_auth_response_without_user_id_is_rejected(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test_key")
    monkeypatch.setattr(
        main.requests,
        "get",
        lambda *args, **kwargs: SimpleNamespace(status_code=200, json=lambda: {"id": ""}),
    )
    response = TestClient(main.app).get(
        "/v1/portfolios",
        headers={"Authorization": "Bearer malformed-auth-response-token"},
    )
    assert response.status_code == 401
    assert "verify your account" in response.json()["detail"].lower()
