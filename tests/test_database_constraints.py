from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.db import (
    Portfolio,
    PortfolioAllocationTarget,
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
        portfolio = Portfolio(name="Constraint Test", currency="INR", owner_user_id="legacy-operator", created_at=now)
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



def test_database_enforces_versioned_target_ranges_and_uniqueness():
    init_db()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        portfolio = Portfolio(
            name="Target Constraint Test",
            currency="INR",
            owner_user_id="target-owner",
            created_at=now,
        )
        db.add(portfolio)
        db.commit()
        portfolio_id = portfolio.id

    with SessionLocal() as db:
        invalid = PortfolioAllocationTarget(
            portfolio_id=portfolio_id,
            owner_user_id="target-owner",
            dimension="ASSET_CLASS",
            target_key="EQUITY",
            min_pct="60",
            target_pct="50",
            max_pct="70",
            effective_from=date(2026, 1, 1),
            priority=100,
            created_at=now,
        )
        db.add(invalid)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    with SessionLocal() as db:
        valid = PortfolioAllocationTarget(
            portfolio_id=portfolio_id,
            owner_user_id="target-owner",
            dimension="ASSET_CLASS",
            target_key="EQUITY",
            min_pct="40",
            target_pct="50",
            max_pct="60",
            effective_from=date(2026, 1, 1),
            priority=100,
            created_at=now,
        )
        db.add(valid)
        db.commit()

    with SessionLocal() as db:
        duplicate = PortfolioAllocationTarget(
            portfolio_id=portfolio_id,
            owner_user_id="target-owner",
            dimension="ASSET_CLASS",
            target_key="EQUITY",
            min_pct="35",
            target_pct="50",
            max_pct="65",
            effective_from=date(2026, 1, 1),
            priority=100,
            created_at=now,
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
