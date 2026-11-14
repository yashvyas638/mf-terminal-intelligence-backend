"""Deny direct Supabase client access to private user tables.

Revision ID: 0027_private_access
Revises: 0026_api_rate_limit_buckets
"""
from alembic import op

revision = "0027_private_access"
down_revision = "0026_api_rate_limit_buckets"
branch_labels = None
depends_on = None

PRIVATE_TABLES = (
    "portfolios",
    "portfolio_transactions",
    "portfolio_transaction_audit",
    "portfolio_import_batches",
    "portfolio_transaction_idempotency",
    "portfolio_goals",
    "portfolio_report_snapshots",
    "fund_watchlist_items",
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table_name in PRIVATE_TABLES:
        op.execute(
            f'REVOKE ALL ON TABLE public."{table_name}" FROM anon, authenticated'
        )
        op.execute(
            f'CREATE POLICY deny_direct_client_access ON public."{table_name}" '
            "FOR ALL TO anon, authenticated USING (false) WITH CHECK (false)"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table_name in PRIVATE_TABLES:
        op.execute(
            f'DROP POLICY IF EXISTS deny_direct_client_access ON public."{table_name}"'
        )
