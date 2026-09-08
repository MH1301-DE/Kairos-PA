"""sync_state_backfill_complete_from

Revision ID: 22f63d4a9f9b
Revises: ad8779b9f2f5
Create Date: 2026-09-08 23:28:06.134540

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '22f63d4a9f9b'
down_revision: Union[str, Sequence[str], None] = 'ad8779b9f2f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('sync_state', sa.Column('backfill_complete_from', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('sync_state', 'backfill_complete_from')
