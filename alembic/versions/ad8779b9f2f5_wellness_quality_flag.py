"""wellness_quality_flag

Revision ID: ad8779b9f2f5
Revises: a3580dcb7b4a
Create Date: 2026-09-08 19:37:59.925709

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ad8779b9f2f5'
down_revision: Union[str, Sequence[str], None] = 'a3580dcb7b4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('wellness_sample', sa.Column('quality', sa.String(length=16), server_default='ok', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('wellness_sample', 'quality')
