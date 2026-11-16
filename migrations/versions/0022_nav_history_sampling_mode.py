"""Add sampling mode to historical NAV checkpoints.

Revision ID: 0022_nav_history_sampling_mode
Revises: 0021_expand_scheme_option_type
"""
from alembic import op
import sqlalchemy as sa

revision = "0022_nav_history_sampling_mode"
down_revision = "0021_expand_scheme_option_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nav_backfill_checkpoints",
        sa.Column(
            "sampling_mode",
            sa.String(length=16),
            nullable=False,
            server_default="daily",
        ),
    )


def downgrade() -> None:
    op.drop_column("nav_backfill_checkpoints", "sampling_mode")
