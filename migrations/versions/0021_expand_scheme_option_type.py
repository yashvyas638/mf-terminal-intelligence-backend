"""Widen scheme option text for historical AMFI descriptions.

Revision ID: 0021_expand_scheme_option_type
Revises: 0020_foreign_key_lookup_indexes
"""
from alembic import op
import sqlalchemy as sa

revision = "0021_expand_scheme_option_type"
down_revision = "0020_foreign_key_lookup_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # AMFI historical Option values are descriptive strings, not just
    # Growth/IDCW labels. Live archives include values up to 82 characters.
    # PostgreSQL enforces VARCHAR length; SQLite does not, so the SQLite
    # migration path needs no physical table rebuild.
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column(
            "schemes",
            "option_type",
            existing_type=sa.String(length=20),
            type_=sa.String(length=160),
            existing_nullable=True,
        )


def downgrade() -> None:
    # Forward-only: historical option descriptions may exceed 20 characters.
    # Narrowing this column would truncate valid source metadata.
    pass
