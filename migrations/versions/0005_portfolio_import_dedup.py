"""Add idempotency records for portfolio CSV imports.

Revision ID: 0005_portfolio_import_dedup
Revises: 0004_supabase_role_lockdown
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_portfolio_import_dedup"
down_revision = "0004_supabase_role_lockdown"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "portfolio_import_batches" in inspector.get_table_names():
        return
    op.create_table(
        "portfolio_import_batches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("statement_sha256", sa.String(length=64), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("imported_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("portfolio_id", "statement_sha256", name="uq_portfolio_import_hash"),
    )
    op.create_index(
        "ix_portfolio_imported_at",
        "portfolio_import_batches",
        ["portfolio_id", "imported_at"],
    )


def downgrade() -> None:
    # Import fingerprints are audit/idempotency evidence; retain them on rollback.
    pass
