"""chases.message_id: the reminder's WhatsApp id, for swipe-replies

Revision ID: b4d6f8a0c2e3
Revises: a9c3e5f7b1d2
Create Date: 2026-11-06 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4d6f8a0c2e3'
down_revision: Union[str, Sequence[str], None] = 'a9c3e5f7b1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('chases', sa.Column('message_id', sa.String(), nullable=True))
    op.create_index(op.f('ix_chases_message_id'), 'chases', ['message_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_chases_message_id'), table_name='chases')
    op.drop_column('chases', 'message_id')
