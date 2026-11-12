"""Align research snapshot windows to 1M, 1Y, 3Y and 5Y.

Revision ID: 0024_research_snapshot_window_horizons
Revises: 0023_screener_period_returns
"""
from alembic import op

revision = "0024_research_snapshot_window_horizons"
down_revision = "0023_screener_period_returns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Research snapshots are a derived cache. Remove the retired 10Y window
    # before tightening the allowed set; the next refresh rebuilds all four
    # supported horizons from accepted NAV observations.
    op.execute(
        "DELETE FROM fund_research_snapshots WHERE window_days = 3650"
    )
    with op.batch_alter_table("fund_research_snapshots") as batch_op:
        batch_op.drop_constraint(
            "ck_fund_research_window_days",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_fund_research_window_days",
            "window_days IN (30, 365, 1095, 1825)",
        )


def downgrade() -> None:
    # Forward-only: do not reintroduce the retired 10Y screener snapshot.
    pass
