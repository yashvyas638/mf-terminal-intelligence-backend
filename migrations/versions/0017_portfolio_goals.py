"""Add owner-isolated financial goal planning records.

Revision ID: 0017_portfolio_goals
Revises: 0016_fund_holdings_disclosures
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_portfolio_goals"
down_revision = "0016_fund_holdings_disclosures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_goals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("target_amount_today", sa.Numeric(20, 2), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("current_amount", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("monthly_contribution", sa.Numeric(20, 2), nullable=False, server_default="0"),
        sa.Column("inflation_rate", sa.Float(), nullable=False, server_default="0.06"),
        sa.Column("annual_return_low", sa.Float(), nullable=False),
        sa.Column("annual_return_base", sa.Float(), nullable=False),
        sa.Column("annual_return_high", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("target_amount_today > 0", name="ck_goal_target_positive"),
        sa.CheckConstraint("current_amount >= 0", name="ck_goal_current_nonnegative"),
        sa.CheckConstraint("monthly_contribution >= 0", name="ck_goal_contribution_nonnegative"),
        sa.CheckConstraint("inflation_rate BETWEEN 0 AND 0.20", name="ck_goal_inflation_bounds"),
        sa.CheckConstraint("annual_return_low BETWEEN -0.20 AND 0.30", name="ck_goal_return_low_bounds"),
        sa.CheckConstraint("annual_return_base BETWEEN -0.20 AND 0.35", name="ck_goal_return_base_bounds"),
        sa.CheckConstraint("annual_return_high BETWEEN -0.20 AND 0.40", name="ck_goal_return_high_bounds"),
        sa.CheckConstraint(
            "annual_return_low <= annual_return_base AND annual_return_base <= annual_return_high",
            name="ck_goal_return_scenarios_order",
        ),
    )
    op.create_index(
        "ix_portfolio_goal_owner_target_date",
        "portfolio_goals",
        ["owner_user_id", "target_date"],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE public.portfolio_goals ENABLE ROW LEVEL SECURITY")
        op.execute("REVOKE ALL ON TABLE public.portfolio_goals FROM PUBLIC, anon, authenticated")
        op.execute("""
            CREATE POLICY portfolio_goal_owner_select
            ON public.portfolio_goals
            FOR SELECT TO authenticated
            USING (owner_user_id = (SELECT auth.uid())::text)
        """)
        op.execute("""
            CREATE POLICY portfolio_goal_owner_insert
            ON public.portfolio_goals
            FOR INSERT TO authenticated
            WITH CHECK (owner_user_id = (SELECT auth.uid())::text)
        """)
        op.execute("""
            CREATE POLICY portfolio_goal_owner_update
            ON public.portfolio_goals
            FOR UPDATE TO authenticated
            USING (owner_user_id = (SELECT auth.uid())::text)
            WITH CHECK (owner_user_id = (SELECT auth.uid())::text)
        """)
        op.execute("""
            CREATE POLICY portfolio_goal_owner_delete
            ON public.portfolio_goals
            FOR DELETE TO authenticated
            USING (owner_user_id = (SELECT auth.uid())::text)
        """)


def downgrade() -> None:
    # Forward-only: preserve saved user goal plans.
    pass
