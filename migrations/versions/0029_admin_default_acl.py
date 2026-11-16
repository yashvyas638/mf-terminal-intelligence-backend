"""Remove Supabase-managed creator defaults that expose future public objects.

Revision ID: 0029_admin_default_acl
Revises: 0028_restrictive_private_access
"""
from alembic import op
from sqlalchemy import text

revision = "0029_admin_default_acl"
down_revision = "0028_restrictive_private_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Supabase-managed supabase_admin defaults may grant anon/authenticated
    # privileges to new public objects. Existing objects are separately audited;
    # this migration closes the future-object path without changing current data.
    role_exists = bind.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = 'supabase_admin'")
    ).scalar_one_or_none()
    if role_exists is None:
        return

    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public "
        "REVOKE ALL ON TABLES FROM anon, authenticated"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public "
        "REVOKE ALL ON SEQUENCES FROM anon, authenticated"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public "
        "REVOKE EXECUTE ON FUNCTIONS FROM anon, authenticated"
    )


def downgrade() -> None:
    # Never reintroduce broad client privileges during a rollback.
    pass
