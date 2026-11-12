"""Add immutable, owner-scoped portfolio report snapshots.

Revision ID: 0018_portfolio_report_snapshots
Revises: 0017_portfolio_goals
"""
from alembic import op
import sqlalchemy as sa

revision = "0018_portfolio_report_snapshots"
down_revision = "0017_portfolio_goals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_report_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "portfolio_id",
            sa.Integer(),
            sa.ForeignKey("portfolios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("report_version", sa.String(length=40), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_max_nav_date", sa.Date(), nullable=True),
    )
    op.create_index(
        "ix_portfolio_report_owner_generated",
        "portfolio_report_snapshots",
        ["owner_user_id", "generated_at"],
    )
    op.create_index(
        "ix_portfolio_report_portfolio_generated",
        "portfolio_report_snapshots",
        ["portfolio_id", "generated_at"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE public.portfolio_report_snapshots ENABLE ROW LEVEL SECURITY")
        op.execute(
            "REVOKE ALL ON TABLE public.portfolio_report_snapshots "
            "FROM PUBLIC, anon, authenticated"
        )


def downgrade() -> None:
    # Forward-only: retain immutable user report history.
    pass
