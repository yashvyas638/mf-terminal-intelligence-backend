"""Reconcile financial trigger functions and pin their safe search_path.

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

    # Some databases were stamped at 0007 before this transaction guard existed.
    # Reconcile the function and trigger here rather than assuming 0007 was
    # executed from the latest source revision.
    op.execute("""
    CREATE OR REPLACE FUNCTION public.protect_portfolio_transaction_mutation()
    RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public
    AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Portfolio transaction facts cannot be deleted; use audited void';
        END IF;
        IF ROW(
            OLD.portfolio_id, OLD.scheme_code, OLD.transaction_type,
            OLD.transaction_date, OLD.units, OLD.nav, OLD.amount,
            OLD.charges, OLD.notes, OLD.created_at
        ) IS DISTINCT FROM ROW(
            NEW.portfolio_id, NEW.scheme_code, NEW.transaction_type,
            NEW.transaction_date, NEW.units, NEW.nav, NEW.amount,
            NEW.charges, NEW.notes, NEW.created_at
        ) THEN
            RAISE EXCEPTION 'Portfolio transaction facts are immutable';
        END IF;
        IF ROW(OLD.voided_at, OLD.void_reason)
            IS DISTINCT FROM ROW(NEW.voided_at, NEW.void_reason) THEN
            IF OLD.voided_at IS NOT NULL OR NEW.voided_at IS NULL
                OR NEW.void_reason IS NULL OR length(trim(NEW.void_reason)) < 3 THEN
                RAISE EXCEPTION 'A transaction may be voided once with a reason; void metadata is immutable';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$;
    """)

    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger
            WHERE tgrelid = 'public.portfolio_transactions'::regclass
              AND tgname = 'trg_portfolio_transactions_immutable'
              AND NOT tgisinternal
        ) THEN
            CREATE TRIGGER trg_portfolio_transactions_immutable
            BEFORE UPDATE OR DELETE ON public.portfolio_transactions
            FOR EACH ROW EXECUTE FUNCTION public.protect_portfolio_transaction_mutation();
        END IF;
    END
    $$;
    """)

    op.execute(
        "ALTER FUNCTION public.prevent_financial_audit_mutation() "
        "SET search_path = pg_catalog, public"
    )
    op.execute(
        "ALTER FUNCTION public.protect_portfolio_transaction_mutation() "
        "SET search_path = pg_catalog, public"
    )


def downgrade() -> None:
    # Keep financial immutability protections during application rollback.
    pass
