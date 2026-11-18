"""Remove duplicate NAV lookup index while retaining the unique constraint index.

Revision ID: 0030_remove_duplicate_nav_index
Revises: 0029_admin_default_acl

The unique constraint uq_nav_scheme_date already provides the exact
(scheme_code, nav_date) B-tree used by NAV lookups. The additional
ix_nav_code_date index duplicates storage and write amplification.
"""
from alembic import op
import sqlalchemy as sa

revision = "0030_remove_duplicate_nav_index"
down_revision = "0029_admin_default_acl"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    inspector = sa.inspect(bind)
    unique_constraints = inspector.get_unique_constraints("nav_observations")
    has_required_unique = any(
        item.get("name") == "uq_nav_scheme_date"
        and item.get("column_names") == ["scheme_code", "nav_date"]
        for item in unique_constraints
    )
    if not has_required_unique:
        raise RuntimeError(
            "Refusing to remove ix_nav_code_date: the matching "
            "uq_nav_scheme_date unique constraint is missing"
        )

    # Avoid holding a long ACCESS EXCLUSIVE lock while the index is removed.
    # Alembic's autocommit block is required by PostgreSQL CONCURRENTLY.
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS public.ix_nav_code_date")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Restore the redundant index only for an explicit rollback to the
    # previous schema. Normal application rollback should not require this.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_nav_code_date "
            "ON public.nav_observations (scheme_code, nav_date)"
        )
