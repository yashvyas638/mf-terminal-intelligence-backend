"""Enforce owner/portfolio consistency for allocation target history.

Revision ID: 0032_target_owner_fk
Revises: 0031_security_mcap
"""
from alembic import op
import sqlalchemy as sa

revision = "0032_target_owner_fk"
down_revision = "0031_security_mcap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    mismatches = bind.execute(sa.text(
        """
        SELECT COUNT(*)
        FROM portfolio_allocation_targets AS target
        LEFT JOIN portfolios AS portfolio
          ON portfolio.id = target.portfolio_id
        WHERE portfolio.id IS NULL
           OR portfolio.owner_user_id <> target.owner_user_id
        """
    )).scalar_one()
    if mismatches:
        raise RuntimeError(
            "Cannot enforce portfolio target ownership: existing target rows "
            "contain missing portfolios or mismatched owner_user_id values."
        )

    # A composite FK requires a unique parent key on (id, owner_user_id).
    op.create_index(
        "uq_portfolio_id_owner_user",
        "portfolios",
        ["id", "owner_user_id"],
        unique=True,
    )

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("portfolio_allocation_targets") as batch:
            batch.create_foreign_key(
                "fk_portfolio_target_owner",
                "portfolios",
                ["portfolio_id", "owner_user_id"],
                ["id", "owner_user_id"],
                ondelete="CASCADE",
            )
    else:
        op.create_foreign_key(
            "fk_portfolio_target_owner",
            "portfolio_allocation_targets",
            "portfolios",
            ["portfolio_id", "owner_user_id"],
            ["id", "owner_user_id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    # Forward-only: preserve allocation policy history and ownership guarantees.
    pass
