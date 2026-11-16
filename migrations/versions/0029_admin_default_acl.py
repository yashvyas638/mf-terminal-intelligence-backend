"""Restrict future public-object privileges for every public-schema creator.

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

    # PostgreSQL's built-in default for new functions is EXECUTE for PUBLIC.
    # A schema-specific REVOKE cannot subtract that global default, so revoke
    # PUBLIC EXECUTE globally for every role that can CREATE in public. Existing
    # functions are unchanged; explicit schema-specific grants remain in force.
    creators = bind.execute(
        text(
            """
            SELECT quote_ident(rolname)
              FROM pg_roles
             WHERE has_schema_privilege(oid, 'public', 'CREATE')
             ORDER BY rolname
            """
        )
    ).scalars().all()

    for creator in creators:
        op.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {creator} "
            "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"
        )
        op.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {creator} IN SCHEMA public "
            "REVOKE ALL ON TABLES FROM anon, authenticated"
        )
        op.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {creator} IN SCHEMA public "
            "REVOKE ALL ON SEQUENCES FROM anon, authenticated"
        )
        op.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {creator} IN SCHEMA public "
            "REVOKE EXECUTE ON FUNCTIONS FROM anon, authenticated"
        )


def downgrade() -> None:
    # Never reintroduce broad client or PUBLIC execution defaults on rollback.
    pass
