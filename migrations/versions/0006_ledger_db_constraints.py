"""Enforce positive NAV and valid financial ledger values in PostgreSQL/SQLite.

Revision ID: 0006_ledger_db_constraints
Revises: 0005_portfolio_import_dedup
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_ledger_db_constraints"
down_revision = "0005_portfolio_import_dedup"
branch_labels = None
depends_on = None


CONSTRAINTS = {
    "nav_observations": [
        ("ck_nav_observation_value_positive", "nav_value > 0"),
    ],
    "portfolio_transactions": [
        ("ck_portfolio_txn_type", "transaction_type IN ('BUY', 'SELL')"),
        ("ck_portfolio_txn_units_positive", "units > 0"),
        ("ck_portfolio_txn_nav_positive", "nav > 0"),
        ("ck_portfolio_txn_amount_positive", "amount > 0"),
        ("ck_portfolio_txn_charges_nonnegative", "charges >= 0"),
    ],
    "portfolio_import_batches": [
        ("ck_portfolio_import_count_positive", "imported_count > 0"),
    ],
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    preflight = {
        "nav_observations": "nav_value <= 0",
        "portfolio_transactions": (
            "transaction_type NOT IN ('BUY', 'SELL') OR units <= 0 OR nav <= 0 "
            "OR amount <= 0 OR charges < 0"
        ),
        "portfolio_import_batches": "imported_count <= 0",
    }
    for table, predicate in preflight.items():
        if table in tables:
            invalid = bind.execute(sa.text(f"SELECT COUNT(*) FROM {table} WHERE {predicate}")).scalar_one()
            if invalid:
                raise RuntimeError(
                    f"Cannot add financial integrity constraints: {table} contains {invalid} invalid rows"
                )

    for table, checks in CONSTRAINTS.items():
        if table not in tables:
            raise RuntimeError(f"Required table {table} is missing; apply earlier migrations first")
        existing = {
            item.get("name")
            for item in sa.inspect(bind).get_check_constraints(table)
        }
        missing = [(name, expression) for name, expression in checks if name not in existing]
        if not missing:
            continue
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table(table) as batch:
                for name, expression in missing:
                    batch.create_check_constraint(name, expression)
        else:
            for name, expression in missing:
                op.create_check_constraint(name, table, expression)


def downgrade() -> None:
    # Keep financial integrity constraints during application rollback.
    pass
