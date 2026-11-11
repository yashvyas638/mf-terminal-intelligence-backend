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
    # checkfirst=True makes this baseline adopt existing deployments created by
    # SQLAlchemy create_all while creating any newly introduced tables.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # Baseline downgrade intentionally does not drop production data.
    pass