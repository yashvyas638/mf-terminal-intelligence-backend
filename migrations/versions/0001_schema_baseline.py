"""Baseline schema, safely adopting databases initialized by create_all.

Revision ID: 0001_schema_baseline
Revises:
"""
from alembic import op
from app.db import Base

revision = "0001_schema_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This table list is intentionally frozen. Future models belong in new revisions.
    baseline_tables = [
        Base.metadata.tables[name]
        for name in (
            "schemes",
            "ingestion_snapshots",
            "nav_observations",
            "portfolios",
            "portfolio_transactions",
            "portfolio_transaction_audit",
        )
    ]
    Base.metadata.create_all(bind=op.get_bind(), tables=baseline_tables, checkfirst=True)


def downgrade() -> None:
    # Baseline downgrade intentionally does not drop production data.
    pass
