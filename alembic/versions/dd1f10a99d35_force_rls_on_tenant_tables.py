"""force_rls_on_tenant_tables

Revision ID: dd1f10a99d35
Revises: 2d0beb5f2474
Create Date: 2026-08-02 21:40:57.559002

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dd1f10a99d35'
down_revision: Union[str, Sequence[str], None] = '2d0beb5f2474'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    for table in ["connection", "raw_payload", "sync_state", "app_user"]:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    for table in ["connection", "raw_payload", "sync_state", "app_user"]:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
