"""Add immutable source-provenanced market-cap classifications.

Revision ID: 0031_security_market_cap_classifications
Revises: 0030_portfolio_allocation_targets
"""
from alembic import op
import sqlalchemy as sa

revision = "0031_security_market_cap_classifications"
down_revision = "0030_portfolio_allocation_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_market_cap_classifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.String(length=12), nullable=False),
        sa.Column("market_cap_bucket", sa.String(length=16), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("source_as_of_date", sa.Date(), nullable=False),
        sa.Column("source_document_url", sa.String(length=1000), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("verification_status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("security_id", "effective_from", "source_sha256", name="uq_security_market_cap_source"),
        sa.CheckConstraint("market_cap_bucket IN ('LARGE_CAP', 'MID_CAP', 'SMALL_CAP', 'OTHER')", name="ck_security_market_cap_bucket"),
        sa.CheckConstraint("verification_status IN ('PENDING', 'VERIFIED', 'REJECTED')", name="ck_security_market_cap_status"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_security_market_cap_effective_range"),
        sa.CheckConstraint("length(source_sha256) = 64", name="ck_security_market_cap_source_hash"),
    )
    op.create_index(
        "ix_security_market_cap_asof",
        "security_market_cap_classifications",
        ["security_id", "effective_from", "effective_to"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE public.security_market_cap_classifications ENABLE ROW LEVEL SECURITY")
        op.execute("REVOKE ALL ON TABLE public.security_market_cap_classifications FROM PUBLIC, anon, authenticated")


def downgrade() -> None:
    # Forward-only: source classification history is retained.
    pass
