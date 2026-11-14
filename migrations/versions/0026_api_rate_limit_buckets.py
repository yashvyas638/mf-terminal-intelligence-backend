"""Add shared database-backed API rate-limit buckets.

Revision ID: 0026_api_rate_limit_buckets
Revises: 0025_portfolio_txn_idempotency
"""
from alembic import op
import sqlalchemy as sa

revision = "0026_api_rate_limit_buckets"
down_revision = "0025_portfolio_txn_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_rate_limit_buckets",
        sa.Column("bucket_sha256", sa.String(length=64), primary_key=True),
        sa.Column("window_start", sa.Integer(), primary_key=True),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(bucket_sha256) = 64",
            name="ck_api_rate_limit_bucket_hash_length",
        ),
        sa.CheckConstraint(
            "request_count > 0",
            name="ck_api_rate_limit_request_count_positive",
        ),
    )
    op.create_index(
        "ix_api_rate_limit_window_start",
        "api_rate_limit_buckets",
        ["window_start"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE public.api_rate_limit_buckets ENABLE ROW LEVEL SECURITY")
        op.execute(
            "REVOKE ALL ON TABLE public.api_rate_limit_buckets "
            "FROM PUBLIC, anon, authenticated"
        )


def downgrade() -> None:
    op.drop_index("ix_api_rate_limit_window_start", table_name="api_rate_limit_buckets")
    op.drop_table("api_rate_limit_buckets")
