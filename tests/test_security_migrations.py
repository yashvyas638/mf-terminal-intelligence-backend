import pytest
from sqlalchemy import text

from app.db import engine


@pytest.mark.skipif(not engine.dialect.name.startswith("postgresql"), reason="PostgreSQL-specific")
def test_supabase_client_roles_cannot_access_public_tables():
    with engine.connect() as connection:
        roles = set(connection.execute(text(
            "SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')"
        )).scalars())
        if not {"anon", "authenticated"}.issubset(roles):
            pytest.skip("Supabase client roles are not present")

        tables = connection.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )).scalars().all()
        for role in ("anon", "authenticated"):
            for table in tables:
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                    allowed = connection.execute(
                        text("SELECT has_table_privilege(:role, :table_name, :privilege)"),
                        {"role": role, "table_name": f"public.{table}", "privilege": privilege},
                    ).scalar_one()
                    assert not allowed, f"{role} unexpectedly has {privilege} on public.{table}"
