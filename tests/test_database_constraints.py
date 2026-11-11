from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.db import (
    IngestionSnapshot,
    Portfolio,
    PortfolioTransaction,
    Scheme,
    SessionLocal,
    init_db,
)


def test_database_rejects_non_positive_portfolio_transaction_units():
    init_db()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        scheme_code = 999994
        if db.get(Scheme, scheme_code) is None:
            db.add(
                Scheme(
                    scheme_code=scheme_code,
                    scheme_name="Constraint Test Fund",
                    isin_growth=None,
                    isin_dividend_reinvestment=None,
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
        portfolio = Portfolio(name="Constraint Test", currency="INR", created_at=now)
        db.add(portfolio)
        db.commit()
        portfolio_id = portfolio.id

    with SessionLocal() as db:
        with pytest.raises(IntegrityError):
            db.add(
                PortfolioTransaction(
                    portfolio_id=portfolio_id,
                    scheme_code=999994,
                    transaction_type="BUY",
                    transaction_date=date(2026, 1, 1),
                    units="-1",
                    nav="100",
                    amount="100",
                    charges="0",
                    created_at=now,
                )
            )
            db.commit()
        db.rollback()
