"""custom_metric_definition

Revision ID: b1025127c2e0
Revises: 7e73ec094ad8
Create Date: 2026-09-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1025127c2e0"
down_revision: str | None = "7e73ec094ad8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "custom_metric_definition",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("expression", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False, server_default="user"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "code", name="uq_custom_metric_definition"),
        sa.CheckConstraint(
            "created_by IN ('user', 'agent')", name="custom_metric_definition_created_by_check"
        ),
    )
    op.execute("ALTER TABLE custom_metric_definition ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON custom_metric_definition "
        "USING (user_id = current_setting('app.current_user_id', true)::uuid)"
    )
    op.execute("ALTER TABLE custom_metric_definition FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON custom_metric_definition")
    op.execute("ALTER TABLE custom_metric_definition NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE custom_metric_definition DISABLE ROW LEVEL SECURITY")
    op.drop_table("custom_metric_definition")
