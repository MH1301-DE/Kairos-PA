"""coach_tables

Revision ID: 9b3e7c1a4d20
Revises: 5d2f8a6c1e47
Create Date: 2026-10-17 18:00:00.000000

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "9b3e7c1a4d20"
down_revision: str | None = "5d2f8a6c1e47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

_NEW_TABLES = ("coach_profile", "athlete_reference_value", "plan_phase", "plan_review")


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        "USING (user_id = current_setting('app.current_user_id', true)::uuid)"
    )
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.create_table(
        "coach_profile",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("plan_type", sa.Text(), nullable=False),
        sa.Column("main_sport", sa.Text(), nullable=False),
        sa.Column(
            "supplementary", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column("availability", postgresql.JSONB(), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("review_weekday", sa.SmallInteger(), nullable=False, server_default="6"),
        sa.Column("review_time", sa.Time(), nullable=False, server_default="19:00"),
        sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.CheckConstraint(
            "main_sport IN ('laufen', 'rad', 'triathlon')", name="coach_profile_main_sport_check"
        ),
        sa.CheckConstraint(
            "review_weekday BETWEEN 0 AND 6", name="coach_profile_review_weekday_check"
        ),
    )

    op.create_table(
        "athlete_reference_value",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("measured_on", sa.Date(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("activity_id", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["activity_id"], ["activity.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "kind IN ('vdot', 'lthr_laufen', 'lthr_rad', 'ftp', 'css', 'critical_speed')",
            name="athlete_reference_value_kind_check",
        ),
        sa.CheckConstraint(
            "source IN ('test', 'wettkampf', 'manuell', 'bestleistung')",
            name="athlete_reference_value_source_check",
        ),
        sa.CheckConstraint("value > 0", name="athlete_reference_value_positive_check"),
    )
    op.create_index(
        "ix_reference_value_current",
        "athlete_reference_value",
        ["user_id", "kind", sa.text("measured_on DESC")],
    )

    # existing phase-5 plans stay valid; several committed ones per user would break S6
    bind = op.get_bind()
    duplicates = bind.execute(
        sa.text(
            "SELECT id, user_id FROM ("
            " SELECT id, user_id, row_number() OVER ("
            "  PARTITION BY user_id ORDER BY updated_at DESC, id DESC) AS rn"
            " FROM plan WHERE status = 'committed') ranked WHERE rn > 1"
        )
    ).all()
    for plan_id, user_id in duplicates:
        logger.warning(
            "coach migration: plan %s of user %s set to abandoned (S6)", plan_id, user_id
        )
    if duplicates:
        bind.execute(
            sa.text("UPDATE plan SET status = 'abandoned' WHERE id = ANY(:ids)"),
            {"ids": [d[0] for d in duplicates]},
        )

    op.add_column("plan", sa.Column("goal_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "plan_goal_id_fkey", "plan", "goal", ["goal_id"], ["id"], ondelete="SET NULL"
    )
    op.add_column("plan", sa.Column("plan_type", sa.Text(), nullable=True))
    op.add_column("plan", sa.Column("plan_type_version", sa.Integer(), nullable=True))
    op.add_column(
        "plan",
        sa.Column("parameters", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column("plan", sa.Column("detail_until", sa.Date(), nullable=True))
    op.drop_constraint("plan_status_check", "plan", type_="check")
    op.create_check_constraint(
        "plan_status_check", "plan", "status IN ('draft', 'committed', 'abandoned', 'completed')"
    )
    op.create_index(
        "uq_plan_active",
        "plan",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'committed'"),
    )

    op.create_table(
        "plan_phase",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.SmallInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("focus", sa.Text(), nullable=True),
        sa.Column("volume_min_km", sa.Float(), nullable=True),
        sa.Column("volume_max_km", sa.Float(), nullable=True),
        sa.Column("rule_refs", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["plan_id"], ["plan.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "seq", name="uq_plan_phase_seq"),
        sa.CheckConstraint(
            "kind IN ('basis', 'aufbau', 'spitze', 'taper', 'wettkampf', 'uebergang')",
            name="plan_phase_kind_check",
        ),
        sa.CheckConstraint("start_date <= end_date", name="plan_phase_dates_check"),
    )

    op.add_column("plan_block", sa.Column("phase_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "plan_block_phase_id_fkey",
        "plan_block",
        "plan_phase",
        ["phase_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("plan_block", sa.Column("sport", sa.Text(), nullable=True))
    op.add_column("plan_block", sa.Column("unit_id", sa.Text(), nullable=True))
    op.add_column("plan_block", sa.Column("start_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("plan_block", sa.Column("planned_duration_s", sa.Integer(), nullable=True))
    op.add_column("plan_block", sa.Column("planned_distance_m", sa.Integer(), nullable=True))
    op.add_column("plan_block", sa.Column("steps", postgresql.JSONB(), nullable=True))
    op.add_column(
        "plan_block",
        sa.Column("rule_refs", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
    )
    op.add_column("plan_block", sa.Column("override_reason", sa.Text(), nullable=True))
    op.add_column("plan_block", sa.Column("activity_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "plan_block_activity_id_fkey",
        "plan_block",
        "activity",
        ["activity_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint("plan_block_workout_type_check", "plan_block", type_="check")
    op.create_check_constraint(
        "plan_block_workout_type_check",
        "plan_block",
        "workout_type IN ('long_run', 'hard', 'easy', 'rest', 'quality', 'strength', 'cross',"
        " 'test')",
    )
    op.drop_constraint("plan_block_status_check", "plan_block", type_="check")
    op.create_check_constraint(
        "plan_block_status_check",
        "plan_block",
        "status IN ('planned', 'done', 'skipped', 'partial', 'replaced')",
    )

    op.create_table(
        "plan_review",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("facts", postgresql.JSONB(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("changes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["plan.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "week_start", name="uq_plan_review_week"),
        sa.CheckConstraint(
            "summary IS NULL OR char_length(summary) <= 1000", name="plan_review_summary_check"
        ),
    )

    for table in _NEW_TABLES:
        _rls(table)


def downgrade() -> None:
    for table in reversed(_NEW_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("plan_review")

    # coach-only values have no phase-5 meaning; map them back before restoring the checks
    op.execute("UPDATE plan_block SET status = 'skipped' WHERE status IN ('partial', 'replaced')")
    op.execute(
        "UPDATE plan_block SET workout_type = CASE workout_type"
        " WHEN 'quality' THEN 'hard' WHEN 'test' THEN 'hard' ELSE 'easy' END"
        " WHERE workout_type IN ('quality', 'strength', 'cross', 'test')"
    )
    op.drop_constraint("plan_block_status_check", "plan_block", type_="check")
    op.create_check_constraint(
        "plan_block_status_check", "plan_block", "status IN ('planned', 'done', 'skipped')"
    )
    op.drop_constraint("plan_block_workout_type_check", "plan_block", type_="check")
    op.create_check_constraint(
        "plan_block_workout_type_check",
        "plan_block",
        "workout_type IN ('long_run', 'hard', 'easy', 'rest')",
    )
    op.drop_constraint("plan_block_activity_id_fkey", "plan_block", type_="foreignkey")
    op.drop_constraint("plan_block_phase_id_fkey", "plan_block", type_="foreignkey")
    for column in (
        "activity_id",
        "override_reason",
        "rule_refs",
        "steps",
        "planned_distance_m",
        "planned_duration_s",
        "start_at",
        "unit_id",
        "sport",
        "phase_id",
    ):
        op.drop_column("plan_block", column)
    op.drop_table("plan_phase")

    op.drop_index("uq_plan_active", table_name="plan")
    op.execute("UPDATE plan SET status = 'abandoned' WHERE status = 'completed'")
    op.drop_constraint("plan_status_check", "plan", type_="check")
    op.create_check_constraint(
        "plan_status_check", "plan", "status IN ('draft', 'committed', 'abandoned')"
    )
    op.drop_constraint("plan_goal_id_fkey", "plan", type_="foreignkey")
    for column in ("detail_until", "parameters", "plan_type_version", "plan_type", "goal_id"):
        op.drop_column("plan", column)

    op.drop_index("ix_reference_value_current", table_name="athlete_reference_value")
    op.drop_table("athlete_reference_value")
    op.drop_table("coach_profile")
