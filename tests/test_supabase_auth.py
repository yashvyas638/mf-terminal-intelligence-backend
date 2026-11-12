from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

import app.main as main
from app.db import init_db


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
