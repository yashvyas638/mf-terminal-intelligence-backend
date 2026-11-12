"""Add source-provenanced benchmark TRI observations and scheme mappings.

Revision ID: 0015_benchmark_tri_foundation
Revises: 0014_fund_research_snapshots
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_benchmark_tri_foundation"
down_revision = "0014_fund_research_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "benchmark_indices",
        sa.Column("benchmark_code", sa.String(length=80), primary_key=True),
        sa.Column("benchmark_name", sa.String(length=240), nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("variant", sa.String(length=8), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("variant IN ('TRI', 'NTR')", name="ck_benchmark_index_total_return_variant"),
    )
    op.create_index(
        "ix_benchmark_provider_name", "benchmark_indices", ["provider", "benchmark_name"]
    )

    op.create_table(
        "benchmark_observations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "benchmark_code",
            sa.String(length=80),
            sa.ForeignKey("benchmark_indices.benchmark_code", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("observation_date", sa.Date(), nullable=False),
        sa.Column("index_value", sa.Numeric(24, 8), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "benchmark_code", "observation_date",
            name="uq_benchmark_observation_date",
        ),
        sa.CheckConstraint("index_value > 0", name="ck_benchmark_index_value_positive"),
    )
    op.create_index(
        "ix_benchmark_observation_code_date",
        "benchmark_observations",
        ["benchmark_code", "observation_date"],
    )

    op.create_table(
        "benchmark_observation_revisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("benchmark_code", sa.String(length=80), nullable=False),
        sa.Column("observation_date", sa.Date(), nullable=False),
        sa.Column("previous_value", sa.Numeric(24, 8), nullable=False),
        sa.Column("replacement_value", sa.Numeric(24, 8), nullable=False),
        sa.Column("previous_source_sha256", sa.String(length=64), nullable=False),
        sa.Column("replacement_source_sha256", sa.String(length=64), nullable=False),
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_benchmark_revision_code_date",
        "benchmark_observation_revisions",
        ["benchmark_code", "observation_date", "corrected_at"],
    )

    op.create_table(
        "scheme_benchmark_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "scheme_code",
            sa.Integer(),
            sa.ForeignKey("schemes.scheme_code", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "benchmark_code",
            sa.String(length=80),
            sa.ForeignKey("benchmark_indices.benchmark_code"),
            nullable=False,
        ),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("source_document_url", sa.String(length=1000), nullable=False),
        sa.Column("source_document_sha256", sa.String(length=64), nullable=False),
        sa.Column("verification_status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("tier IN (1, 2)", name="ck_scheme_benchmark_tier"),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_scheme_benchmark_effective_dates",
        ),
        sa.CheckConstraint(
            "verification_status IN ('PENDING', 'VERIFIED', 'REJECTED')",
            name="ck_scheme_benchmark_verification_status",
        ),
        sa.UniqueConstraint(
            "scheme_code", "tier", "valid_from",
            name="uq_scheme_benchmark_tier_start",
        ),
    )
    op.create_index(
        "ix_scheme_benchmark_active",
        "scheme_benchmark_assignments",
        ["scheme_code", "verification_status", "valid_from", "valid_to"],
    )

    if op.get_bind().dialect.name == "postgresql":
        for table in (
            "benchmark_indices",
            "benchmark_observations",
            "benchmark_observation_revisions",
            "scheme_benchmark_assignments",
        ):
            op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
            op.execute(
                f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC, anon, authenticated"
            )


def downgrade() -> None:
    # Forward-only: preserve benchmark provenance and effective-dated mappings.
    pass
