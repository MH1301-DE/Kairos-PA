"""connection_token_refresh_tracking

Revision ID: b3c1e2f4a5d6
Revises: a7f9f3d1c2b4
Create Date: 2026-08-05 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3c1e2f4a5d6"
down_revision: Union[str, None] = "a7f9f3d1c2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("connection", sa.Column("token_refreshed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("connection", sa.Column("reauth_since", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("connection", "reauth_since")
    op.drop_column("connection", "token_refreshed_at")
