"""PostgreSQL integration assertions for migration 0010 RLS and ACL hardening."""
import pytest
from sqlalchemy import text

from app.db import engine


pytestmark = pytest.mark.skipif(
    not engine.dialect.name.startswith("postgresql"),
    reason="PostgreSQL-specific RLS and ACL checks",
)


def test_all_public_tables_have_rls_enabled():
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT c.relname, c.relrowsecurity
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
        """)).all()
    assert rows, "expected application tables in public schema"
    assert all(enabled for _, enabled in rows), rows


def test_public_and_supabase_client_roles_have_no_table_or_sequence_access():
    with engine.connect() as connection:
        tables = connection.execute(text("""
            SELECT c.relname
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
        """)).scalars().all()
        sequences = connection.execute(text("""
            SELECT c.relname
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relkind = 'S'
        """)).scalars().all()
        roles = ["PUBLIC", "anon", "authenticated"]
        for role in roles:
            for table in tables:
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                    if role == "PUBLIC":
                        allowed = connection.execute(text("""
                            SELECT EXISTS (
                                SELECT 1 FROM aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
                                WHERE a.grantee = 0 AND a.privilege_type = :privilege
                            )
                            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                            WHERE n.nspname = 'public' AND c.relname = :name
                        """), {"privilege": privilege, "name": table}).scalar_one()
                    else:
                        allowed = connection.execute(text(
                            "SELECT has_table_privilege(:role, :name, :privilege)"
                        ), {"role": role, "name": f"public.{table}", "privilege": privilege}).scalar_one()
                    assert not allowed, f"{role} has {privilege} on public.{table}"
            for sequence in sequences:
                for privilege in ("USAGE", "SELECT", "UPDATE"):
                    if role == "PUBLIC":
                        allowed = connection.execute(text("""
                            SELECT EXISTS (
                                SELECT 1 FROM aclexplode(coalesce(c.relacl, acldefault('S', c.relowner))) a
                                WHERE a.grantee = 0 AND a.privilege_type = :privilege
                            )
                            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                            WHERE n.nspname = 'public' AND c.relname = :name
                        """), {"privilege": privilege, "name": sequence}).scalar_one()
                    else:
                        allowed = connection.execute(text(
                            "SELECT has_sequence_privilege(:role, :name, :privilege)"
                        ), {"role": role, "name": f"public.{sequence}", "privilege": privilege}).scalar_one()
                    assert not allowed, f"{role} has {privilege} on public.{sequence}"


def test_public_cannot_execute_public_schema_functions():
    with engine.connect() as connection:
        functions = connection.execute(text("""
            SELECT p.oid::regprocedure::text
              FROM pg_proc p
              JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE n.nspname = 'public' AND p.prokind = 'f'
        """)).scalars().all()
        for signature in functions:
            allowed = connection.execute(text(
                "SELECT has_function_privilege('public', :signature, 'EXECUTE')"
            ), {"signature": signature}).scalar_one()
            assert not allowed, f"PUBLIC can execute {signature}"
