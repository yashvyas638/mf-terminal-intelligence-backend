"""Remove the duplicate non-unique NAV lookup index.

Revision ID: 0033_remove_duplicate_nav_index
Revises: 0032_target_owner_fk

The uq_nav_scheme_date unique constraint already provides the same ordered
(scheme_code, nav_date) B-tree lookup path. Keep that constraint and the
surrogate primary key; remove only the duplicate non-unique index.
"""
from alembic import op
import sqlalchemy as sa

revision = "0033_remove_duplicate_nav_index"
down_revision = "0032_target_owner_fk"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_nav_code_date"


def upgrade() -> None:
    bind = op.get_bind()
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("nav_observations")}
    if INDEX_NAME in indexes:
        op.drop_index(INDEX_NAME, table_name="nav_observations")


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("nav_observations")}
    if INDEX_NAME not in indexes:
        op.create_index(INDEX_NAME, "nav_observations", ["scheme_code", "nav_date"], unique=False)
