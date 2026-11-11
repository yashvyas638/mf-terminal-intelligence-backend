"""Make financial audit and NAV correction provenance append-only.

Revision ID: 0007_append_only_audit
Revises: 0006_ledger_db_constraints
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_append_only_audit"
down_revision = "0006_ledger_db_constraints"
branch_labels = None
depends_on = None


TABLES = ("portfolio_transaction_audit", "nav_observation_revisions")


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table in TABLES:
        if table not in tables:
            raise RuntimeError(f"Required append-only table {table} is missing")

    if bind.dialect.name == "postgresql":
        op.execute("""
        CREATE OR REPLACE FUNCTION prevent_financial_audit_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'Financial audit/provenance records are append-only';
        END;
        $$;
        """)
        for table in TABLES:
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
    elif bind.dialect.name == "sqlite":
        for table in TABLES:
            for operation in ("UPDATE", "DELETE"):
                trigger = f"trg_{table}_no_{operation.lower()}"
                op.execute(f"""
                CREATE TRIGGER IF NOT EXISTS {trigger}
                BEFORE {operation} ON {table}
                BEGIN
                    SELECT RAISE(ABORT, 'Financial audit/provenance records are append-only');
                END;
                """)


def downgrade() -> None:
    # Do not remove audit immutability automatically during application rollback.
    pass
