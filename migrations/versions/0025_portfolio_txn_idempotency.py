"""Add durable idempotency for single portfolio transaction creation.

Revision ID: 0025_portfolio_txn_idempotency
Revises: 0024_research_windows
"""
from alembic import op
import sqlalchemy as sa

revision = "0025_portfolio_txn_idempotency"
down_revision = "0024_research_windows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_transaction_idempotency",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "portfolio_id", sa.Integer(),
            sa.ForeignKey("portfolios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "transaction_id", sa.Integer(),
            sa.ForeignKey("portfolio_transactions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("response_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "portfolio_id", "idempotency_key",
            name="uq_portfolio_transaction_idempotency_key",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 128",
            name="ck_portfolio_txn_idempotency_key_length",
        ),
        sa.CheckConstraint(
            "length(request_sha256) = 64",
            name="ck_portfolio_txn_idempotency_hash_length",
        ),
    )
    op.create_index(
        "ix_portfolio_txn_idempotency_created",
        "portfolio_transaction_idempotency",
        ["portfolio_id", "created_at"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE public.portfolio_transaction_idempotency ENABLE ROW LEVEL SECURITY"
        )
        op.execute(
            "REVOKE ALL ON TABLE public.portfolio_transaction_idempotency "
            "FROM PUBLIC, anon, authenticated"
        )


def downgrade() -> None:
    # Forward-only: request replay history is retained across application rollbacks.
    pass
