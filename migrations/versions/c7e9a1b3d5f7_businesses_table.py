"""businesses table: a display name for each business

Revision ID: c7e9a1b3d5f7
Revises: b4d6f8a0c2e3
Create Date: 2026-11-06 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7e9a1b3d5f7'
down_revision: Union[str, Sequence[str], None] = 'b4d6f8a0c2e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('businesses',
    sa.Column('business_id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=True),
    sa.Column('whatsapp_name', sa.String(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('business_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('businesses')
