"""activity_derived_tables

Revision ID: 5d2f8a6c1e47
Revises: 3b9e5c7a1d24
Create Date: 2026-10-15 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "5d2f8a6c1e47"
down_revision: str | None = "3b9e5c7a1d24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("activity_stats", "activity_split", "activity_best_effort", "activity_step_result")

_REAL = postgresql.REAL()
_SMALL = sa.SmallInteger()


def _fks() -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(["activity_id"], ["activity.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
    ]


def upgrade() -> None:
    op.create_table(
        "activity_stats",
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("sport_profile", sa.Text(), nullable=False),
        sa.Column("algo_version", _SMALL, nullable=False),
        sa.Column("distance_m", _REAL, nullable=True),
        sa.Column("elapsed_s", _REAL, nullable=True),
        sa.Column("timer_s", _REAL, nullable=True),
        sa.Column("moving_s", _REAL, nullable=True),
        sa.Column("avg_pace_s_km", _REAL, nullable=True),
        sa.Column("avg_moving_pace_s_km", _REAL, nullable=True),
        sa.Column("avg_speed_kmh", _REAL, nullable=True),
        sa.Column("max_speed_kmh", _REAL, nullable=True),
        sa.Column("avg_pace_s_100m", _REAL, nullable=True),
        sa.Column("hr_avg", _SMALL, nullable=True),
        sa.Column("hr_median", _SMALL, nullable=True),
        sa.Column("hr_min", _SMALL, nullable=True),
        sa.Column("hr_max", _SMALL, nullable=True),
        sa.Column("hr_zone_s", postgresql.JSONB(), nullable=True),
        sa.Column("trimp_edwards", _REAL, nullable=True),
        sa.Column("elev_gain_m", _REAL, nullable=True),
        sa.Column("elev_loss_m", _REAL, nullable=True),
        sa.Column("alt_min_m", _REAL, nullable=True),
        sa.Column("alt_max_m", _REAL, nullable=True),
        sa.Column("cadence_avg", _REAL, nullable=True),
        sa.Column("power_avg_w", _REAL, nullable=True),
        sa.Column("power_max_w", _REAL, nullable=True),
        sa.Column("fastest_split_idx", _SMALL, nullable=True),
        sa.Column("fastest_split_pace_s", _REAL, nullable=True),
        sa.Column("slowest_split_idx", _SMALL, nullable=True),
        sa.Column("slowest_split_pace_s", _REAL, nullable=True),
        sa.Column("pace_cv_pct", _REAL, nullable=True),
        sa.Column("decoupling_pct", _REAL, nullable=True),
        sa.Column("decoupling_note", sa.Text(), nullable=True),
        sa.Column("distance_source", sa.Text(), nullable=True),
        sa.Column("hr_coverage_pct", _REAL, nullable=True),
        sa.Column("gps_coverage_pct", _REAL, nullable=True),
        sa.Column("quality", sa.Text(), nullable=False),
        sa.Column(
            "sport_metrics", postgresql.JSONB(), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        *_fks(),
        sa.PrimaryKeyConstraint("activity_id"),
        sa.CheckConstraint(
            "distance_source IN ('gps','watch_estimate','pool','mixed','none')",
            name="activity_stats_distance_source_check",
        ),
        sa.CheckConstraint(
            "quality IN ('ok','partial','suspect')", name="activity_stats_quality_check"
        ),
    )
    op.create_table(
        "activity_split",
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("idx", _SMALL, nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("unit_m", _REAL, nullable=True),
        sa.Column("start_offset_s", _REAL, nullable=True),
        sa.Column("distance_m", _REAL, nullable=True),
        sa.Column("timer_s", _REAL, nullable=True),
        sa.Column("pace_s_km", _REAL, nullable=True),
        sa.Column("speed_kmh", _REAL, nullable=True),
        sa.Column("pace_s_100m", _REAL, nullable=True),
        sa.Column("elev_gain_m", _REAL, nullable=True),
        sa.Column("elev_loss_m", _REAL, nullable=True),
        sa.Column("hr_min", _SMALL, nullable=True),
        sa.Column("hr_median", _SMALL, nullable=True),
        sa.Column("hr_max", _SMALL, nullable=True),
        sa.Column("hr_avg", _SMALL, nullable=True),
        sa.Column("cadence_avg", _REAL, nullable=True),
        sa.Column("power_avg_w", _REAL, nullable=True),
        sa.Column("is_partial", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("lap_intensity", sa.Text(), nullable=True),
        sa.Column("lap_trigger", sa.Text(), nullable=True),
        sa.Column("wkt_step_index", _SMALL, nullable=True),
        sa.Column("swim_lengths", _SMALL, nullable=True),
        sa.Column("swolf", _REAL, nullable=True),
        sa.Column("quality", sa.Text(), nullable=False),
        *_fks(),
        sa.PrimaryKeyConstraint("activity_id", "kind", "idx"),
        sa.CheckConstraint("kind IN ('distance','lap')", name="activity_split_kind_check"),
    )
    op.create_table(
        "activity_best_effort",
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.Column("distance_key", sa.Text(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("distance_m", _REAL, nullable=False),
        sa.Column("duration_s", _REAL, nullable=False),
        sa.Column("start_offset_s", _REAL, nullable=False),
        sa.Column("start_km", _REAL, nullable=False),
        sa.Column("hr_avg", _SMALL, nullable=True),
        sa.Column("quality", sa.Text(), nullable=False),
        *_fks(),
        sa.PrimaryKeyConstraint("activity_id", "distance_key"),
    )
    op.create_table(
        "activity_step_result",
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.Column("exec_idx", _SMALL, nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("wkt_step_index", _SMALL, nullable=False),
        sa.Column("repeat_iteration", _SMALL, nullable=True),
        sa.Column("step_type", sa.Text(), nullable=False),
        sa.Column("step_note", sa.Text(), nullable=True),
        sa.Column("planned_end", sa.Text(), nullable=True),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_low", _REAL, nullable=True),
        sa.Column("target_high", _REAL, nullable=True),
        sa.Column("target_source", sa.Text(), nullable=True),
        sa.Column("secondary_type", sa.Text(), nullable=True),
        sa.Column("secondary_low", _REAL, nullable=True),
        sa.Column("secondary_high", _REAL, nullable=True),
        sa.Column("timer_s", _REAL, nullable=True),
        sa.Column("distance_m", _REAL, nullable=True),
        sa.Column("avg_pace_s_km", _REAL, nullable=True),
        sa.Column("avg_hr", _REAL, nullable=True),
        sa.Column("hr_in_target_pct", _REAL, nullable=True),
        sa.Column("avg_cadence", _REAL, nullable=True),
        sa.Column("avg_power_w", _REAL, nullable=True),
        sa.Column("hit", sa.Boolean(), nullable=True),
        sa.Column("secondary_hit", sa.Boolean(), nullable=True),
        *_fks(),
        sa.PrimaryKeyConstraint("activity_id", "exec_idx"),
        sa.CheckConstraint(
            "target_source IN ('fit', 'api', 'unclear', 'none')",
            name="activity_step_result_target_source_check",
        ),
    )
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (user_id = current_setting('app.current_user_id', true)::uuid)"
        )
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_table(table)
