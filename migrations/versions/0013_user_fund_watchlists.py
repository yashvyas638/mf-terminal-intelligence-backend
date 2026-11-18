"""Add isolated per-user fund watchlists.

Revision ID: 0013_user_fund_watchlists
Revises: 0012_nav_backfill_checkpoints
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_user_fund_watchlists"
down_revision = "0012_nav_backfill_checkpoints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fund_watchlist_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "scheme_code",
            sa.Integer(),
            sa.ForeignKey("schemes.scheme_code", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "owner_user_id", "scheme_code",
            name="uq_fund_watchlist_owner_scheme",
        ),
    )
    op.create_index(
        "ix_fund_watchlist_owner_created",
        "fund_watchlist_items",
        ["owner_user_id", "created_at"],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE public.fund_watchlist_items ENABLE ROW LEVEL SECURITY")
        op.execute(
            "REVOKE ALL ON TABLE public.fund_watchlist_items "
            "FROM PUBLIC, anon, authenticated"
        )
        op.execute("""
            CREATE POLICY fund_watchlist_owner_select
            ON public.fund_watchlist_items
            FOR SELECT TO authenticated
            USING (owner_user_id = (SELECT auth.uid())::text)
        """)
        op.execute("""
            CREATE POLICY fund_watchlist_owner_insert
            ON public.fund_watchlist_items
            FOR INSERT TO authenticated
            WITH CHECK (owner_user_id = (SELECT auth.uid())::text)
        """)
        op.execute("""
            CREATE POLICY fund_watchlist_owner_delete
            ON public.fund_watchlist_items
            FOR DELETE TO authenticated
            USING (owner_user_id = (SELECT auth.uid())::text)
        """)


def downgrade() -> None:
    # Forward-only: saved user research should not be removed by an app rollback.
    pass
