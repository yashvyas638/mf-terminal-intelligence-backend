"""Link financial goals to owner-scoped portfolios.

Revision ID: 0019_goal_portfolio_link
Revises: 0018_portfolio_report_snapshots
"""
from alembic import op
import sqlalchemy as sa

revision = "0019_goal_portfolio_link"
down_revision = "0018_portfolio_report_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "portfolio_goals",
        sa.Column("linked_portfolio_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_portfolio_goals_linked_portfolio",
        "portfolio_goals",
        "portfolios",
        ["linked_portfolio_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_portfolio_goal_linked_portfolio",
        "portfolio_goals",
        ["linked_portfolio_id"],
    )


def downgrade() -> None:
    # Forward-only: retain goal-to-portfolio relationships.
    pass
