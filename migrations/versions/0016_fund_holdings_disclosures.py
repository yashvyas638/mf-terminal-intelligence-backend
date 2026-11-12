"""Add immutable, source-provenanced fund holdings disclosures.

Revision ID: 0016_fund_holdings_disclosures
Revises: 0015_benchmark_tri_foundation
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_fund_holdings_disclosures"
down_revision = "0015_benchmark_tri_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fund_holding_disclosures",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "scheme_code",
            sa.Integer(),
            sa.ForeignKey("schemes.scheme_code", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("source_document_url", sa.String(length=1000), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("total_weight_pct", sa.Numeric(14, 8), nullable=False),
        sa.Column("verification_status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "supersedes_disclosure_id",
            sa.Integer(),
            sa.ForeignKey("fund_holding_disclosures.id"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "scheme_code", "as_of_date", "source_sha256",
            name="uq_holding_disclosure_source",
        ),
        sa.CheckConstraint("row_count > 0", name="ck_holding_disclosure_row_count"),
        sa.CheckConstraint(
            "verification_status IN ('PENDING', 'VERIFIED', 'REJECTED')",
            name="ck_holding_disclosure_verification_status",
        ),
    )
    op.create_index(
        "ix_holding_disclosure_scheme_date",
        "fund_holding_disclosures",
        ["scheme_code", "as_of_date", "retrieved_at"],
    )

    op.create_table(
        "fund_holdings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "disclosure_id",
            sa.Integer(),
            sa.ForeignKey("fund_holding_disclosures.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("security_id", sa.String(length=80), nullable=False),
        sa.Column("security_name", sa.String(length=240), nullable=False),
        sa.Column("is_isin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("asset_type", sa.String(length=80), nullable=True),
        sa.Column("sector", sa.String(length=120), nullable=True),
        sa.Column("weight_pct", sa.Numeric(14, 8), nullable=False),
        sa.Column("market_value_inr", sa.Numeric(24, 2), nullable=True),
        sa.UniqueConstraint(
            "disclosure_id", "security_id",
            name="uq_holding_disclosure_security",
        ),
        sa.CheckConstraint(
            "weight_pct BETWEEN -1000 AND 1000",
            name="ck_fund_holding_weight_bounds",
        ),
    )
    op.create_index(
        "ix_fund_holding_disclosure_security",
        "fund_holdings",
        ["disclosure_id", "security_id"],
    )
    op.create_index(
        "ix_fund_holding_security",
        "fund_holdings",
        ["security_id", "is_isin"],
    )

    if op.get_bind().dialect.name == "postgresql":
        for table in ("fund_holding_disclosures", "fund_holdings"):
            op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
            op.execute(
                f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC, anon, authenticated"
            )


def downgrade() -> None:
    # Forward-only: retain portfolio disclosure provenance.
    pass
