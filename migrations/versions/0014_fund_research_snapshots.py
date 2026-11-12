"""Add precomputed NAV research snapshots for global screener ranking.

Revision ID: 0014_fund_research_snapshots
Revises: 0013_user_fund_watchlists
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_fund_research_snapshots"
down_revision = "0013_user_fund_watchlists"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fund_research_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "scheme_code",
            sa.Integer(),
            sa.ForeignKey("schemes.scheme_code", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("nav_as_of_date", sa.Date(), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observations", sa.Integer(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("return_1m", sa.Float(), nullable=True),
        sa.Column("return_1y", sa.Float(), nullable=True),
        sa.Column("return_3y", sa.Float(), nullable=True),
        sa.Column("cagr", sa.Float(), nullable=True),
        sa.Column("volatility", sa.Float(), nullable=True),
        sa.Column("sharpe_ratio", sa.Float(), nullable=True),
        sa.Column("sortino_ratio", sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("positive_month_rate", sa.Float(), nullable=True),
        sa.Column("rolling_1y_positive_rate", sa.Float(), nullable=True),
        sa.UniqueConstraint(
            "scheme_code", "window_days",
            name="uq_fund_research_scheme_window",
        ),
        sa.CheckConstraint(
            "window_days IN (365, 1095, 1825, 3650)",
            name="ck_fund_research_window_days",
        ),
        sa.CheckConstraint(
            "observations >= 0",
            name="ck_fund_research_observations_nonnegative",
        ),
    )
    op.create_index(
        "ix_fund_research_window_return_1y",
        "fund_research_snapshots",
        ["window_days", "return_1y"],
    )
    op.create_index(
        "ix_fund_research_window_sharpe",
        "fund_research_snapshots",
        ["window_days", "sharpe_ratio"],
    )
    op.create_index(
        "ix_fund_research_window_cagr",
        "fund_research_snapshots",
        ["window_days", "cagr"],
    )

    if op.get_bind().dialect.name == "postgresql":
        # The server's trusted DB connection serves this shared market-data
        # cache. Browser roles must not query or mutate it directly.
        op.execute("ALTER TABLE public.fund_research_snapshots ENABLE ROW LEVEL SECURITY")
        op.execute(
            "REVOKE ALL ON TABLE public.fund_research_snapshots "
            "FROM PUBLIC, anon, authenticated"
        )


def downgrade() -> None:
    # Forward-only: preserve historical research snapshots across app rollbacks.
    pass
