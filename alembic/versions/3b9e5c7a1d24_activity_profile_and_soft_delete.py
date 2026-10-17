"""activity_profile_and_soft_delete

Revision ID: 3b9e5c7a1d24
Revises: fed6d2d1311b
Create Date: 2026-10-14 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "3b9e5c7a1d24"
down_revision: str | None = "fed6d2d1311b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "activity",
        sa.Column("sport_profile", sa.Text(), nullable=False, server_default="generic"),
    )
    op.add_column("activity", sa.Column("garmin_type_id", sa.Integer(), nullable=True))
    op.add_column("activity", sa.Column("garmin_parent_type_id", sa.Integer(), nullable=True))
    op.add_column("activity", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("activity", sa.Column("start_local", sa.DateTime(), nullable=True))
    op.add_column("activity", sa.Column("utc_offset_min", sa.SmallInteger(), nullable=True))
    op.add_column("activity", sa.Column("moving_duration_s", postgresql.REAL(), nullable=True))
    op.add_column("activity", sa.Column("avg_speed_mps", postgresql.REAL(), nullable=True))
    op.add_column("activity", sa.Column("lap_count", sa.SmallInteger(), nullable=True))
    op.add_column("activity", sa.Column("garmin_training_load", postgresql.REAL(), nullable=True))
    op.add_column("activity", sa.Column("garmin_vo2max", postgresql.REAL(), nullable=True))
    op.add_column("activity", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("activity", sa.Column("deleted_reason", sa.Text(), nullable=True))
    op.create_check_constraint(
        "activity_sport_profile_check",
        "activity",
        "sport_profile IN ('running', 'cycling', 'swimming', 'hiking', 'generic')",
    )
    op.create_check_constraint(
        "activity_deleted_reason_check",
        "activity",
        "deleted_reason IS NULL OR deleted_reason IN ('kairos', 'garmin_sync')",
    )
    op.drop_column("activity", "activity_type")
    op.create_index(
        "ix_activity_user_start_live",
        "activity",
        ["user_id", sa.text("start_at DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_activity_user_profile_start",
        "activity",
        ["user_id", "sport_profile", sa.text("start_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_activity_user_profile_start", table_name="activity")
    op.drop_index("ix_activity_user_start_live", table_name="activity")
    op.add_column("activity", sa.Column("activity_type", sa.Text(), nullable=True))
    op.drop_constraint("activity_deleted_reason_check", "activity", type_="check")
    op.drop_constraint("activity_sport_profile_check", "activity", type_="check")
    for col in (
        "deleted_reason",
        "deleted_at",
        "garmin_vo2max",
        "garmin_training_load",
        "lap_count",
        "avg_speed_mps",
        "moving_duration_s",
        "utc_offset_min",
        "start_local",
        "description",
        "garmin_parent_type_id",
        "garmin_type_id",
        "sport_profile",
    ):
        op.drop_column("activity", col)
