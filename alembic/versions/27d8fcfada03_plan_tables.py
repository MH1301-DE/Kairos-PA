"""plan_tables

Revision ID: 27d8fcfada03
Revises: c409728c466e
Create Date: 2026-09-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "27d8fcfada03"
down_revision: str | None = "c409728c466e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plan",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("goal_date", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('draft', 'committed', 'abandoned')", name="plan_status_check"
        ),
    )
    op.execute("ALTER TABLE plan ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON plan "
        "USING (user_id = current_setting('app.current_user_id', true)::uuid)"
    )
    op.execute("ALTER TABLE plan FORCE ROW LEVEL SECURITY")

    op.create_table(
        "plan_block",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        # redundant to plan.user_id, but needed directly here so this table's
        # own RLS policy doesn't need a subquery/join (same reasoning as
        # conversation_message.user_id)
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("workout_type", sa.Text(), nullable=False),
        sa.Column("target_trimp", sa.Float(), nullable=True),
        sa.Column("calendar_event_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="planned"),
        sa.ForeignKeyConstraint(["plan_id"], ["plan.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["calendar_event_id"], ["calendar_event.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "workout_type IN ('long_run', 'hard', 'easy', 'rest')",
            name="plan_block_workout_type_check",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'done', 'skipped')", name="plan_block_status_check"
        ),
    )
    op.execute("ALTER TABLE plan_block ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON plan_block "
        "USING (user_id = current_setting('app.current_user_id', true)::uuid)"
    )
    op.execute("ALTER TABLE plan_block FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON plan_block")
    op.execute("ALTER TABLE plan_block NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE plan_block DISABLE ROW LEVEL SECURITY")
    op.drop_table("plan_block")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON plan")
    op.execute("ALTER TABLE plan NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE plan DISABLE ROW LEVEL SECURITY")
    op.drop_table("plan")
