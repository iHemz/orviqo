"""processed_messages table

Revision ID: f1a4d7b2c8e0
Revises: e3b8c1d05f92
Create Date: 2026-07-13 20:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a4d7b2c8e0'
down_revision: Union[str, Sequence[str], None] = 'e3b8c1d05f92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('processed_messages',
    sa.Column('message_id', sa.String(), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('message_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('processed_messages')
