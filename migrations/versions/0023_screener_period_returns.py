"""Persist all displayed trailing-period returns for screener sorting.

Revision ID: 0023_screener_period_returns
Revises: 0022_nav_history_sampling_mode
"""
from alembic import op
import sqlalchemy as sa

revision = "0023_screener_period_returns"
down_revision = "0022_nav_history_sampling_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fund_research_snapshots", sa.Column("return_3m", sa.Float(), nullable=True))
    op.add_column("fund_research_snapshots", sa.Column("return_6m", sa.Float(), nullable=True))
    op.add_column("fund_research_snapshots", sa.Column("return_5y", sa.Float(), nullable=True))
    op.create_index(
        "ix_fund_research_window_return_3m",
        "fund_research_snapshots",
        ["window_days", "return_3m"],
    )
    op.create_index(
        "ix_fund_research_window_return_6m",
        "fund_research_snapshots",
        ["window_days", "return_6m"],
    )
    op.create_index(
        "ix_fund_research_window_return_5y",
        "fund_research_snapshots",
        ["window_days", "return_5y"],
    )


def downgrade() -> None:
    # Forward-only: preserve research snapshots and their ranking fields.
    pass
