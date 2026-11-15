"""Make private-table client denial policies restrictive.

Revision ID: 0028_restrictive_private_access
Revises: 0027_private_access
"""
from alembic import op

revision = "0028_restrictive_private_access"
down_revision = "0027_private_access"
branch_labels = None
depends_on = None

PRIVATE_TABLES = (
    "portfolio_transaction_idempotency",
    "portfolio_goals",
    "portfolio_report_snapshots",
    "fund_watchlist_items",
    "api_rate_limit_buckets",
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table_name in PRIVATE_TABLES:
        op.execute(
            f'DROP POLICY IF EXISTS deny_direct_client_access ON public."{table_name}"'
        )
        op.execute(
            f'CREATE POLICY deny_direct_client_access ON public."{table_name}" '
            "AS RESTRICTIVE FOR ALL TO anon, authenticated "
            "USING (false) WITH CHECK (false)"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table_name in PRIVATE_TABLES:
        op.execute(
            f'DROP POLICY IF EXISTS deny_direct_client_access ON public."{table_name}"'
        )
        op.execute(
            f'CREATE POLICY deny_direct_client_access ON public."{table_name}" '
            "FOR ALL TO anon, authenticated USING (false) WITH CHECK (false)"
        )
