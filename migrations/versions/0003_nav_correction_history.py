"""Preserve superseded AMFI NAV values as append-only corrections.

Revision ID: 0003_nav_correction_history
Revises: 0002_portfolio_ledger_audit
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_nav_correction_history"
down_revision = "0002_portfolio_ledger_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "nav_observation_revisions" not in inspector.get_table_names():
        op.create_table(
            "nav_observation_revisions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("scheme_code", sa.Integer(), sa.ForeignKey("schemes.scheme_code"), nullable=False),
            sa.Column("nav_date", sa.Date(), nullable=False),
            sa.Column("previous_nav_value", sa.Numeric(20, 8), nullable=False),
            sa.Column("replacement_nav_value", sa.Numeric(20, 8), nullable=False),
            sa.Column("previous_source_snapshot_id", sa.Integer(), sa.ForeignKey("ingestion_snapshots.id"), nullable=False),
            sa.Column("replacement_source_snapshot_id", sa.Integer(), sa.ForeignKey("ingestion_snapshots.id"), nullable=False),
            sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_nav_revision_code_date",
            "nav_observation_revisions",
            ["scheme_code", "nav_date", "corrected_at"],
        )


def downgrade() -> None:
    # Keep financial correction provenance during application rollback.
    # An approved archival procedure is required to remove this table.
    pass
