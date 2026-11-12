from datetime import date, datetime, timezone
import json

import pytest
from fastapi.testclient import TestClient

from app.db import FundResearchSnapshot, Scheme, SessionLocal, init_db
from app.main import app


@pytest.mark.parametrize(
    ("sort_by", "expected"),
    [
        ("return_3m", 0.031),
        ("return_6m", 0.062),
        ("return_5y", 0.51),
    ],
)
def test_screener_sorts_and_returns_every_displayed_period(monkeypatch, sort_by, expected):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    init_db()
    now = datetime.now(timezone.utc)
    scheme_code = 99123456 + {"return_3m": 1, "return_6m": 2, "return_5y": 3}[sort_by]

    with SessionLocal() as db:
        if db.get(Scheme, scheme_code) is None:
            db.add(Scheme(
                scheme_code=scheme_code,
                scheme_name="Period Ranking Verification Fund",
                isin_growth=None,
                isin_dividend_reinvestment=None,
                first_seen_at=now,
                last_seen_at=now,
                category_group="Equity Scheme",
                category="Flexi Cap Fund",
                asset_class="Equity",
                plan_type="Direct",
                option_type="Growth",
            ))
        db.flush()
        db.add(FundResearchSnapshot(
            scheme_code=scheme_code,
            window_days=3650,
            nav_as_of_date=date.today(),
            refreshed_at=now,
            observations=39,
            metrics_json=json.dumps({
                "status": "OK",
                "latest_nav": 123.45,
                "period_returns": {
                    "1M": 0.01,
                    "3M": 0.031,
                    "6M": 0.062,
                    "1Y": 0.12,
                    "3Y": 0.31,
                    "5Y": 0.51,
                },
            }),
            return_1m=0.01,
            return_3m=0.031,
            return_6m=0.062,
            return_1y=0.12,
            return_3y=0.31,
            return_5y=0.51,
            cagr=0.085,
            volatility=0.14,
            sharpe_ratio=0.9,
            sortino_ratio=1.1,
            max_drawdown=-0.18,
            positive_month_rate=0.61,
            rolling_1y_positive_rate=0.72,
        ))
        db.commit()

    response = TestClient(app).get(
        f"/v1/analytics/screener?days=3650&sort_by={sort_by}&q={scheme_code}",
        headers={"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"},
    )
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item[sort_by] == pytest.approx(expected)
