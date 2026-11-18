"""Protect financial audit, import fingerprints and transaction facts.

Revision ID: 0007_append_only_audit
Revises: 0006_ledger_db_constraints
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_append_only_audit"
down_revision = "0006_ledger_db_constraints"
branch_labels = None
depends_on = None

APPEND_ONLY_TABLES = (
    "portfolio_transaction_audit",
    "nav_observation_revisions",
    "portfolio_import_batches",
)


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    required = set(APPEND_ONLY_TABLES) | {"portfolio_transactions"}
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError(f"Required financial integrity tables are missing: {missing}")

    if bind.dialect.name == "postgresql":
        op.execute("""
        CREATE OR REPLACE FUNCTION prevent_financial_audit_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            RAISE EXCEPTION 'Financial audit/provenance records are append-only';
        END;
        $$;
        """)
        for table in APPEND_ONLY_TABLES:
            trigger = f"trg_{table}_append_only"
            op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = '{trigger}' AND NOT tgisinternal
                ) THEN
                    CREATE TRIGGER {trigger}
                    BEFORE UPDATE OR DELETE ON {table}
                    FOR EACH ROW EXECUTE FUNCTION prevent_financial_audit_mutation();
                END IF;
            END
            $$;
            """)
        op.execute("""
        CREATE OR REPLACE FUNCTION protect_portfolio_transaction_mutation()
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
                WHERE tgname = 'trg_portfolio_transactions_immutable' AND NOT tgisinternal
            ) THEN
                CREATE TRIGGER trg_portfolio_transactions_immutable
                BEFORE UPDATE OR DELETE ON portfolio_transactions
                FOR EACH ROW EXECUTE FUNCTION protect_portfolio_transaction_mutation();
            END IF;
        END
        $$;
        """)
    elif bind.dialect.name == "sqlite":
        for table in APPEND_ONLY_TABLES:
            for operation in ("UPDATE", "DELETE"):
                trigger = f"trg_{table}_no_{operation.lower()}"
                op.execute(f"""
                CREATE TRIGGER IF NOT EXISTS {trigger}
                BEFORE {operation} ON {table}
                BEGIN
                    SELECT RAISE(ABORT, 'Financial audit/provenance records are append-only');
                END;
                """)
        op.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_portfolio_transactions_no_delete
        BEFORE DELETE ON portfolio_transactions
        BEGIN
            SELECT RAISE(ABORT, 'Portfolio transaction facts cannot be deleted; use audited void');
        END;
        """)
        op.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_portfolio_transactions_immutable
        BEFORE UPDATE ON portfolio_transactions
        WHEN
            OLD.portfolio_id IS NOT NEW.portfolio_id
            OR OLD.scheme_code IS NOT NEW.scheme_code
            OR OLD.transaction_type IS NOT NEW.transaction_type
            OR OLD.transaction_date IS NOT NEW.transaction_date
            OR OLD.units IS NOT NEW.units
            OR OLD.nav IS NOT NEW.nav
            OR OLD.amount IS NOT NEW.amount
            OR OLD.charges IS NOT NEW.charges
            OR OLD.notes IS NOT NEW.notes
            OR OLD.created_at IS NOT NEW.created_at
            OR (
                (OLD.voided_at IS NOT NEW.voided_at OR OLD.void_reason IS NOT NEW.void_reason)
                AND (
                    OLD.voided_at IS NOT NULL
                    OR NEW.voided_at IS NULL
                    OR NEW.void_reason IS NULL
                    OR length(trim(NEW.void_reason)) < 3
                )
            )
        BEGIN
            SELECT RAISE(ABORT, 'Portfolio transaction facts are immutable; use audited void');
        END;
        """)


def downgrade() -> None:
    # Keep financial immutability protections during application rollback.
    pass
