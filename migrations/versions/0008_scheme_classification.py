"""Add AMFI-derived scheme classification fields for the research layer.

Revision ID: 0008_scheme_classification
Revises: 0007_append_only_audit

Classification is nullable: existing schemes are populated on the next validated
NAV refresh. No historical financial records are changed.
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_scheme_classification"
down_revision = "0007_append_only_audit"
branch_labels = None
depends_on = None

COLUMNS = (
    ("amc", sa.String(length=200)),
    ("structure", sa.String(length=40)),
    ("category_group", sa.String(length=120)),
    ("category", sa.String(length=160)),
    ("asset_class", sa.String(length=40)),
    ("plan_type", sa.String(length=20)),
    ("option_type", sa.String(length=20)),
)


def upgrade() -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("schemes")}
    for name, type_ in COLUMNS:
        if name not in existing:
            op.add_column("schemes", sa.Column(name, type_, nullable=True))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("schemes")}
    if "ix_schemes_category_plan_option" not in indexes:
        op.create_index(
            "ix_schemes_category_plan_option",
            "schemes",
            ["category", "plan_type", "option_type"],
            unique=False,
        )


def downgrade() -> None:
    # Classification is non-financial metadata. Keep it on rollback to avoid
    # destroying derived data; a later forward migration can change its schema.
    pass
