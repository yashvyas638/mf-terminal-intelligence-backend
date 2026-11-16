import json
from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main
from app.db import Base, FundResearchSnapshot, Scheme


def test_monthly_leaderboard_bootstraps_missing_research_snapshots(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(main, "SessionLocal", test_session_factory)
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")

    def fake_refresh(x_api_key):
        now = datetime.now(timezone.utc)
        with test_session_factory.begin() as db:
            db.add(Scheme(
                scheme_code=99187654,
                scheme_name="Monthly Leaderboard Bootstrap Fund",
                isin_growth=None,
                isin_dividend_reinvestment=None,
                first_seen_at=now,
                last_seen_at=now,
                category_group="Equity Scheme",
                category="Flexi Cap Fund",
                plan_type="Direct",
                option_type="Growth",
            ))
            db.flush()
            db.add(FundResearchSnapshot(
                scheme_code=99187654,
                window_days=365,
                nav_as_of_date=date.today(),
                refreshed_at=now,
                observations=12,
                metrics_json=json.dumps({
                    "monthly_returns": [
                        {"month": "2026-09", "return": 0.02},
                        {"month": "2026-10", "return": 0.03},
                    ],
                }),
                return_1m=0.01,
                return_3m=0.03,
                return_6m=0.06,
                return_1y=0.12,
                return_3y=None,
                return_5y=None,
                cagr=0.12,
                volatility=0.14,
                sharpe_ratio=0.8,
                sortino_ratio=1.0,
                max_drawdown=-0.1,
                positive_month_rate=0.6,
                rolling_1y_positive_rate=0.7,
            ))
            db.add(Scheme(
                scheme_code=99187655,
                scheme_name="Unclassified Monthly Fund",
                isin_growth=None,
                isin_dividend_reinvestment=None,
                first_seen_at=now,
                last_seen_at=now,
                category_group="Equity Scheme",
                category=None,
                plan_type="Direct",
                option_type="Growth",
            ))
            db.add(FundResearchSnapshot(
                scheme_code=99187655,
                window_days=365,
                nav_as_of_date=date.today(),
                refreshed_at=now,
                observations=12,
                metrics_json=json.dumps({
                    "monthly_returns": [
                        {"month": "2026-09", "return": 0.01},
                        {"month": "2026-10", "return": 0.08},
                    ],
                }),
                return_1m=0.02,
                return_3m=0.04,
                return_6m=0.07,
                return_1y=0.13,
                return_3y=None,
                return_5y=None,
                cagr=0.13,
                volatility=0.15,
                sharpe_ratio=0.9,
                sortino_ratio=1.1,
                max_drawdown=-0.1,
                positive_month_rate=0.6,
                rolling_1y_positive_rate=0.7,
            ))
        return {
            "status": "refreshed",
            "schemes_processed": 1,
            "snapshot_rows_written": 1,
            "refreshed_at": now.isoformat(),
        }

    monkeypatch.setattr(main, "refresh_fund_research_snapshots", fake_refresh)
    response = TestClient(main.app).get(
        "/v1/analytics/monthly-leaderboard?month=2026-10",
        headers={"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["month"] == "2026-10"
    assert payload["count"] == 1
    assert payload["items"][0]["scheme_code"] == 99187654
    assert payload["items"][0]["monthly_return"] == 0.03
