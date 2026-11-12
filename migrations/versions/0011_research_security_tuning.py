"""Tune RLS evaluation and index foreign-key access paths.

Revision ID: 0011_research_security_tuning
Revises: 0010_user_auth_rls
"""
from alembic import op

revision = "0011_research_security_tuning"
down_revision = "0010_user_auth_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # RLS policies and function privileges are PostgreSQL/Supabase-specific.
    # Keep SQLite migration coverage useful for the portable schema/index layer.
    if dialect == "postgresql":
        # Cache auth.uid() once per statement instead of re-evaluating it per row.
        op.execute("DROP POLICY IF EXISTS portfolios_owner_read ON public.portfolios")
        op.execute("""
            CREATE POLICY portfolios_owner_read ON public.portfolios
            FOR SELECT TO authenticated
            USING (owner_user_id = (SELECT auth.uid())::text)
        """)
        op.execute("DROP POLICY IF EXISTS portfolio_transactions_owner_read ON public.portfolio_transactions")
        op.execute("""
            CREATE POLICY portfolio_transactions_owner_read ON public.portfolio_transactions
            FOR SELECT TO authenticated USING (
                EXISTS (
                    SELECT 1 FROM public.portfolios p
                    WHERE p.id = portfolio_transactions.portfolio_id
                      AND p.owner_user_id = (SELECT auth.uid())::text
                )
            )
        """)
        op.execute("DROP POLICY IF EXISTS portfolio_import_batches_owner_read ON public.portfolio_import_batches")
        op.execute("""
            CREATE POLICY portfolio_import_batches_owner_read ON public.portfolio_import_batches
            FOR SELECT TO authenticated USING (
                EXISTS (
                    SELECT 1 FROM public.portfolios p
                    WHERE p.id = portfolio_import_batches.portfolio_id
                      AND p.owner_user_id = (SELECT auth.uid())::text
                )
            )
        """)
        op.execute("DROP POLICY IF EXISTS portfolio_transaction_audit_owner_read ON public.portfolio_transaction_audit")
        op.execute("""
            CREATE POLICY portfolio_transaction_audit_owner_read ON public.portfolio_transaction_audit
            FOR SELECT TO authenticated USING (
                EXISTS (
                    SELECT 1
                    FROM public.portfolio_transactions t
                    JOIN public.portfolios p ON p.id = t.portfolio_id
                    WHERE t.id = portfolio_transaction_audit.transaction_id
                      AND p.owner_user_id = (SELECT auth.uid())::text
                )
            )
        """)

        # Trigger functions are invoked by triggers, not browser RPC clients.
        op.execute(
            "REVOKE EXECUTE ON FUNCTION public.prevent_financial_audit_mutation() "
            "FROM PUBLIC, anon, authenticated"
        )
        op.execute(
            "REVOKE EXECUTE ON FUNCTION public.protect_portfolio_transaction_mutation() "
            "FROM PUBLIC, anon, authenticated"
        )

    # Index foreign-key columns used by joins and referential checks.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_nav_observations_source_snapshot "
        "ON public.nav_observations (source_snapshot_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_nav_revisions_previous_snapshot "
        "ON public.nav_observation_revisions (previous_source_snapshot_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_nav_revisions_replacement_snapshot "
        "ON public.nav_observation_revisions (replacement_source_snapshot_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_portfolio_transactions_scheme_code "
        "ON public.portfolio_transactions (scheme_code)"
    )


def downgrade() -> None:
    # Forward-only security/performance hardening.
    pass
