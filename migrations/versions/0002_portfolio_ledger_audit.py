"""Add immutable portfolio-ledger audit records and transaction voids.

Revision ID: 0002_portfolio_ledger_audit
Revises: 0001_schema_baseline
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_portfolio_ledger_audit"
down_revision = "0001_schema_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    transaction_columns = {column["name"] for column in inspector.get_columns("portfolio_transactions")}
    if "voided_at" not in transaction_columns or "void_reason" not in transaction_columns:
        with op.batch_alter_table("portfolio_transactions") as batch_op:
            if "voided_at" not in transaction_columns:
                batch_op.add_column(sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True))
            if "void_reason" not in transaction_columns:
                batch_op.add_column(sa.Column("void_reason", sa.String(length=500), nullable=True))
    if "portfolio_transaction_audit" not in inspector.get_table_names():
        op.create_table(
            "portfolio_transaction_audit",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("transaction_id", sa.Integer(), sa.ForeignKey("portfolio_transactions.id"), nullable=False),
            sa.Column("event_type", sa.String(length=32), nullable=False),
            sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("details_json", sa.Text(), nullable=False),
        )
        op.create_index("ix_txn_audit_transaction_event", "portfolio_transaction_audit", ["transaction_id", "event_at"])


def downgrade() -> None:
    op.drop_index("ix_txn_audit_transaction_event", table_name="portfolio_transaction_audit")
    op.drop_table("portfolio_transaction_audit")
    with op.batch_alter_table("portfolio_transactions") as batch_op:
        batch_op.drop_column("void_reason")
        batch_op.drop_column("voided_at")