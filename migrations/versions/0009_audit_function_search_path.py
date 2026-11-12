"""Pin a safe search_path on financial immutability trigger functions.

Revision ID: 0009_audit_function_search_path
Revises: 0008_scheme_classification
"""
from alembic import op

revision = "0009_audit_function_search_path"
down_revision = "0008_scheme_classification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER FUNCTION public.prevent_financial_audit_mutation() SET search_path = pg_catalog, public")
    op.execute("ALTER FUNCTION public.protect_portfolio_transaction_mutation() SET search_path = pg_catalog, public")


def downgrade() -> None:
    # Keep hardened function resolution during application rollback.
    pass
