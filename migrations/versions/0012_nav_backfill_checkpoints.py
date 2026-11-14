"""Add durable AMFI NAV history backfill checkpoints.

Revision ID: 0012_nav_backfill_checkpoints
Revises: 0011_research_security_tuning
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_nav_backfill_checkpoints"
down_revision = "0011_research_security_tuning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nav_backfill_checkpoints",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("window_key", sa.String(length=64), nullable=False),
        sa.Column("scheme_type", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_sha256", sa.String(length=64), nullable=True),
        sa.Column("records_valid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inserted_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unchanged_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_class", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("window_key", name="uq_nav_backfill_window_key"),
        sa.CheckConstraint("scheme_type IN (1, 2, 3)", name="ck_nav_backfill_scheme_type"),
        sa.CheckConstraint("end_date >= start_date", name="ck_nav_backfill_date_range"),
        sa.CheckConstraint("status IN ('pending', 'running', 'complete', 'failed', 'paused')", name="ck_nav_backfill_status"),
        sa.CheckConstraint("attempts >= 0", name="ck_nav_backfill_attempts_nonnegative"),
        sa.CheckConstraint(
            "records_valid >= 0 AND inserted_rows >= 0 AND updated_rows >= 0 "
            "AND unchanged_rows >= 0 AND duplicate_rows >= 0 AND invalid_rows >= 0",
            name="ck_nav_backfill_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "(status = 'complete' AND completed_at IS NOT NULL) OR "
            "(status <> 'complete' AND completed_at IS NULL)",
            name="ck_nav_backfill_completion_consistent",
        ),
    )
    op.create_index(
        "ix_nav_backfill_status_dates", "nav_backfill_checkpoints",
        ["status", "start_date", "end_date"],
    )
    op.create_index(
        "ix_nav_backfill_type_dates", "nav_backfill_checkpoints",
        ["scheme_type", "start_date", "end_date"],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE public.nav_backfill_checkpoints ENABLE ROW LEVEL SECURITY")
        op.execute(
            "REVOKE ALL ON TABLE public.nav_backfill_checkpoints "
            "FROM PUBLIC, anon, authenticated"
        )


def downgrade() -> None:
    # Forward-only: retain durable job history and avoid accidental loss of
    # checkpoint evidence during an application rollback.
    pass
