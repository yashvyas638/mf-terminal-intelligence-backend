import json
from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from app.db import FundResearchSnapshot, Scheme, SessionLocal, init_db
from app.main import app
import app.main as main


def test_monthly_leaderboard_returns_top_funds_for_each_subcategory(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key-that-is-at-least-32-characters-long")
    monkeypatch.setattr(main, "_research_snapshots_are_current", lambda: True)
    init_db()
    now = datetime.now(timezone.utc)
    codes = (99877101, 99877102, 99877103, 99877104)
    records = (
        ("Monthly Flexi Leader A", "Flexi Cap Fund", 0.05, 0.03),
        ("Monthly Flexi Leader B", "Flexi Cap Fund", 0.03, 0.04),
        ("Monthly Large Leader A", "Large Cap Fund", 0.045, 0.02),
        ("Monthly Large Leader B", "Large Cap Fund", 0.015, 0.01),
    )

    with SessionLocal() as db:
        db.query(FundResearchSnapshot).filter(
            FundResearchSnapshot.scheme_code.in_(codes)
        ).delete(synchronize_session=False)
        db.query(Scheme).filter(Scheme.scheme_code.in_(codes)).delete(
            synchronize_session=False
        )
        db.commit()

        for code, (name, category, october_return, september_return) in zip(
            codes, records, strict=True
        ):
            db.add(Scheme(
                scheme_code=code,
                scheme_name=name,
                isin_growth=None,
                isin_dividend_reinvestment=None,
                first_seen_at=now,
                last_seen_at=now,
                category_group="Equity Scheme",
                category=category,
                asset_class="Equity",
                plan_type="Direct Plan",
                option_type="Growth Option",
            ))
            db.add(FundResearchSnapshot(
                scheme_code=code,
                window_days=365,
                nav_as_of_date=date.today(),
                refreshed_at=now,
                observations=250,
                metrics_json=json.dumps({
                    "monthly_returns": [
                        {"month": "2026-09", "return": september_return},
                        {"month": "2026-10", "return": october_return},
                    ],
                }),
                return_1m=0.01,
                return_1y=0.12,
                return_3y=None,
                return_5y=None,
                cagr=0.10,
                volatility=0.15,
                sharpe_ratio=0.8,
                sortino_ratio=1.0,
                max_drawdown=-0.12,
                positive_month_rate=0.6,
                rolling_1y_positive_rate=0.7,
            ))
        db.commit()

    response = TestClient(app).get(
        "/v1/analytics/monthly-leaderboard?month=2026-10&category_group=Equity+Scheme&plan_type=Direct&option_type=Growth&limit=1",
        headers={"X-API-Key": "test-api-key-that-is-at-least-32-characters-long"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    # Preserve the existing broad-group top-N response for API compatibility.
    assert payload["count"] == 4
    assert [item["scheme_code"] for item in payload["items"]] == [codes[0]]
    assert payload["items"][0]["category_rank"] == 1

    # New category breakdown returns a top-N list within every canonical peer group.
    assert payload["category_count"] == 2
    assert [item["category"] for item in payload["categories"]] == [
        "Flexi Cap Fund",
        "Large Cap Fund",
    ]
    assert [item["count"] for item in payload["categories"]] == [2, 2]
    assert [item["items"][0]["scheme_code"] for item in payload["categories"]] == [
        codes[0],
        codes[2],
    ]
    assert [item["items"][0]["category_rank"] for item in payload["categories"]] == [1, 1]
