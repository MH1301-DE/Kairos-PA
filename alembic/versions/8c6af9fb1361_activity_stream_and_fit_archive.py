"""activity_stream_and_fit_archive

Revision ID: 8c6af9fb1361
Revises: 5c8e1d2f7a90
Create Date: 2026-10-14 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "8c6af9fb1361"
down_revision: str | None = "5c8e1d2f7a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RLS_TABLES = ("activity_stream_axis", "activity_stream")


def upgrade() -> None:
    used = op.get_bind().execute(
        sa.text("SELECT count(*) FROM activity WHERE fit_object_key IS NOT NULL")
    ).scalar_one()
    if used:
        raise RuntimeError(f"activity.fit_object_key has {used} non-NULL rows; refusing to drop")

    op.add_column(
        "raw_payload",
        sa.Column("payload_format", sa.Text(), nullable=False, server_default="json_gzip"),
    )
    op.create_check_constraint(
        "raw_payload_payload_format_check",
        "raw_payload",
        "payload_format IN ('json_gzip', 'fit_zip')",
    )
    op.drop_column("activity", "fit_object_key")
    op.add_column("activity", sa.Column("fit_payload_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "activity_fit_payload_id_fkey", "activity", "raw_payload",
        ["fit_payload_id"], ["id"], ondelete="SET NULL",
    )

    op.create_table(
        "activity_stream_axis",
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("t_offset_s", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("algo_version", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["activity.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("activity_id"),
        sa.CheckConstraint(
            "source IN ('fit_zip', 'fit_json')", name="activity_stream_axis_source_check"
        ),
    )
    op.create_table(
        "activity_stream",
        sa.Column("activity_id", sa.BigInteger(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("v4", postgresql.ARRAY(postgresql.REAL()), nullable=True),
        sa.Column("v8", postgresql.ARRAY(postgresql.DOUBLE_PRECISION()), nullable=True),
        sa.ForeignKeyConstraint(["activity_id"], ["activity.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("activity_id", "channel"),
        sa.CheckConstraint("num_nonnulls(v4, v8) = 1", name="activity_stream_one_array_check"),
    )
    op.execute("ALTER TABLE activity_stream_axis ALTER COLUMN t_offset_s SET COMPRESSION lz4")
    op.execute("ALTER TABLE activity_stream ALTER COLUMN v4 SET COMPRESSION lz4")
    op.execute("ALTER TABLE activity_stream ALTER COLUMN v8 SET COMPRESSION lz4")
    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (user_id = current_setting('app.current_user_id', true)::uuid)"
        )
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in reversed(_RLS_TABLES):
        op.drop_table(table)
    op.drop_constraint("activity_fit_payload_id_fkey", "activity", type_="foreignkey")
    op.drop_column("activity", "fit_payload_id")
    op.add_column("activity", sa.Column("fit_object_key", sa.Text(), nullable=True))
    op.drop_constraint("raw_payload_payload_format_check", "raw_payload", type_="check")
    op.drop_column("raw_payload", "payload_format")
