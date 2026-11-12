"""Enable RLS and close Supabase client-role grants on public objects.

Revision ID: 0010_rls_hardening
Revises: 0009_audit_function_search_path

This migration is intentionally fail-closed. It only enables RLS when the
migration connection is superuser, BYPASSRLS, or owns every public table.
"""
from alembic import op

revision = "0010_rls_hardening"
down_revision = "0009_audit_function_search_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # Never apply RLS-without-policies for a backend role that would be filtered.
    op.execute("""
    DO $preflight$
    DECLARE
        role_name text := current_user;
        is_super boolean;
        can_bypass boolean;
        table_count integer;
        owned_count integer;
    BEGIN
        SELECT rolsuper, rolbypassrls
          INTO is_super, can_bypass
          FROM pg_roles WHERE rolname = role_name;

        SELECT count(*),
               count(*) FILTER (WHERE pg_get_userbyid(c.relowner) = role_name)
          INTO table_count, owned_count
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relkind IN ('r','p');

        IF NOT coalesce(is_super, false)
           AND NOT coalesce(can_bypass, false)
           AND (table_count = 0 OR owned_count <> table_count) THEN
            RAISE EXCEPTION
              'Refusing RLS hardening: migration role % neither owns every public table nor bypasses RLS',
              role_name;
        END IF;
    END
    $preflight$;
    """)

    op.execute("""
    DO $hardening$
    DECLARE
        t record;
        r text;
        f record;
    BEGIN
        -- Enable, do not FORCE: table owners retain normal owner access.
        FOR t IN
            SELECT c.relname
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relkind IN ('r','p')
        LOOP
            EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.relname);
        END LOOP;

        -- Supabase client roles must not access this backend-only data model.
        FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', r);
                EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', r);
                EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM %I', r);
                EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM %I', r);
                EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM %I', r);
                EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM %I', r);
            END IF;
        END LOOP;

        -- PUBLIC is a pseudo-role and must be handled separately.
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
        REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC;
        REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM PUBLIC;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM PUBLIC;

        -- Pin search_path on all overloads of both financial trigger functions.
        FOR f IN
            SELECT p.oid::regprocedure AS signature
              FROM pg_proc p
              JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE n.nspname = 'public'
               AND p.proname IN (
                   'prevent_financial_audit_mutation',
                   'protect_portfolio_transaction_mutation'
               )
        LOOP
            EXECUTE format('ALTER FUNCTION %s SET search_path = pg_catalog, public', f.signature);
        END LOOP;
    END
    $hardening$;
    """)


def downgrade() -> None:
    # Deliberately no-op: re-opening client grants or disabling RLS must be a
    # separate, reviewed operational action, never an automatic code rollback.
    pass
