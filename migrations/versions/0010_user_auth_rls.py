"""Introduce authenticated portfolio ownership and database RLS.

Revision ID: 0010_user_auth_rls
Revises: 0009_audit_function_search_path
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_user_auth_rls"
down_revision = "0009_audit_function_search_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        columns = {column["name"] for column in sa.inspect(bind).get_columns("portfolios")}
        if "owner_user_id" not in columns:
            op.add_column("portfolios", sa.Column("owner_user_id", sa.String(length=36), nullable=True))
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes("portfolios")}
        if "ix_portfolios_owner_user_id" not in indexes:
            op.create_index("ix_portfolios_owner_user_id", "portfolios", ["owner_user_id"], unique=False)
        return

    columns = {column["name"] for column in sa.inspect(bind).get_columns("portfolios")}
    if "owner_user_id" not in columns:
        op.add_column("portfolios", sa.Column("owner_user_id", sa.String(length=36), nullable=True))

    # Never silently assign historical records to whichever user signs in first.
    # If a legacy portfolio exists, stop the deployment and require an explicit owner mapping.
    legacy_count = bind.execute(sa.text(
        "SELECT count(*) FROM public.portfolios WHERE owner_user_id IS NULL"
    )).scalar_one()
    if legacy_count:
        raise RuntimeError(
            f"Migration blocked: {legacy_count} legacy portfolio(s) have no verified owner. "
            "Map each portfolio to its confirmed Supabase Auth user before retrying."
        )

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("portfolios")}
    if "ix_portfolios_owner_user_id" not in indexes:
        op.create_index("ix_portfolios_owner_user_id", "portfolios", ["owner_user_id"], unique=False)
    op.alter_column("portfolios", "owner_user_id", existing_type=sa.String(length=36), nullable=False)

    # RLS is enabled for every public table. The browser never receives database
    # credentials; portfolio reads are exposed only through the owner-scoped API.
    for table in (
        "alembic_version", "schemes", "ingestion_snapshots", "portfolios",
        "nav_observations", "portfolio_transactions", "portfolio_transaction_audit",
        "nav_observation_revisions", "portfolio_import_batches",
    ):
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')

    # Remove any accidental direct client privileges first.
    op.execute(
        "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, anon, authenticated"
    )
    op.execute(
        "GRANT SELECT ON public.schemes, public.nav_observations TO authenticated"
    )
    op.execute(
        "GRANT SELECT ON public.portfolios, public.portfolio_transactions, "
        "public.portfolio_transaction_audit, public.portfolio_import_batches TO authenticated"
    )

    op.execute("""
        CREATE POLICY schemes_authenticated_read ON public.schemes
        FOR SELECT TO authenticated USING (true)
    """)
    op.execute("""
        CREATE POLICY nav_observations_authenticated_read ON public.nav_observations
        FOR SELECT TO authenticated USING (true)
    """)
    op.execute("""
        CREATE POLICY portfolios_owner_read ON public.portfolios
        FOR SELECT TO authenticated USING (owner_user_id = auth.uid()::text)
    """)
    op.execute("""
        CREATE POLICY portfolio_transactions_owner_read ON public.portfolio_transactions
        FOR SELECT TO authenticated USING (
            EXISTS (
                SELECT 1 FROM public.portfolios p
                WHERE p.id = portfolio_transactions.portfolio_id
                  AND p.owner_user_id = auth.uid()::text
            )
        )
    """)
    op.execute("""
        CREATE POLICY portfolio_import_batches_owner_read ON public.portfolio_import_batches
        FOR SELECT TO authenticated USING (
            EXISTS (
                SELECT 1 FROM public.portfolios p
                WHERE p.id = portfolio_import_batches.portfolio_id
                  AND p.owner_user_id = auth.uid()::text
            )
        )
    """)
    op.execute("""
        CREATE POLICY portfolio_transaction_audit_owner_read ON public.portfolio_transaction_audit
        FOR SELECT TO authenticated USING (
            EXISTS (
                SELECT 1
                FROM public.portfolio_transactions t
                JOIN public.portfolios p ON p.id = t.portfolio_id
                WHERE t.id = portfolio_transaction_audit.transaction_id
                  AND p.owner_user_id = auth.uid()::text
            )
        )
    """)


def downgrade() -> None:
    # Forward-only: do not remove ownership or re-open direct client access.
    pass
