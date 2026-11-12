"""Index uncovered foreign-key lookup paths.

Revision ID: 0020_foreign_key_lookup_indexes
Revises: 0019_goal_portfolio_link
"""
from alembic import op
import sqlalchemy as sa

revision = "0020_foreign_key_lookup_indexes"
down_revision = "0019_goal_portfolio_link"
branch_labels = None
depends_on = None

INDEXES = (
    ("fund_holding_disclosures", "ix_fund_holding_disclosures_supersedes_id", ("supersedes_disclosure_id",)),
    ("fund_watchlist_items", "ix_fund_watchlist_items_scheme_code", ("scheme_code",)),
    ("scheme_benchmark_assignments", "ix_scheme_benchmark_assignments_benchmark_code", ("benchmark_code",)),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table_name, index_name, columns in INDEXES:
        existing = {item["name"] for item in inspector.get_indexes(table_name)}
        if index_name not in existing:
            op.create_index(index_name, table_name, list(columns), unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table_name, index_name, _columns in reversed(INDEXES):
        existing = {item["name"] for item in inspector.get_indexes(table_name)}
        if index_name in existing:
            op.drop_index(index_name, table_name=table_name)
