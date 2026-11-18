"""Add versioned owner-scoped portfolio allocation target bands.

Revision ID: 0030_portfolio_allocation_targets
Revises: 0029_admin_default_acl
"""
from alembic import op
import sqlalchemy as sa

revision = "0030_portfolio_targets"
down_revision = "0029_admin_default_acl"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_allocation_targets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("target_key", sa.String(length=160), nullable=False),
        sa.Column("min_pct", sa.Numeric(9, 4), nullable=False),
        sa.Column("target_pct", sa.Numeric(9, 4), nullable=False),
        sa.Column("max_pct", sa.Numeric(9, 4), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "portfolio_id", "dimension", "target_key", "effective_from", "version",
            name="uq_portfolio_target_version_key",
        ),
        sa.CheckConstraint(
            "dimension IN ('ASSET_CLASS', 'CATEGORY', 'SUB_CATEGORY', 'MARKET_CAP', 'AMC', 'SCHEME', 'SECTOR')",
            name="ck_portfolio_target_dimension",
        ),
        sa.CheckConstraint(
            "min_pct >= 0 AND min_pct <= target_pct AND target_pct <= max_pct AND max_pct <= 100",
            name="ck_portfolio_target_band_bounds",
        ),
        sa.CheckConstraint("version >= 1", name="ck_portfolio_target_version_positive"),
        sa.CheckConstraint("priority BETWEEN 1 AND 1000", name="ck_portfolio_target_priority_bounds"),
    )
    op.create_index(
        "ix_portfolio_target_owner_effective",
        "portfolio_allocation_targets",
        ["owner_user_id", "portfolio_id", "dimension", "effective_from"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE public.portfolio_allocation_targets ENABLE ROW LEVEL SECURITY")
        op.execute("REVOKE ALL ON TABLE public.portfolio_allocation_targets FROM PUBLIC, anon, authenticated")


def downgrade() -> None:
    # Forward-only: preserve user-defined allocation history.
    pass
