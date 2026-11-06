"""chase_holds table: promises to pay and disputes pause chasing

Revision ID: e5a7c9b1d3f6
Revises: d2f4a6c8e0b1
Create Date: 2026-11-06 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a7c9b1d3f6'
down_revision: Union[str, Sequence[str], None] = 'd2f4a6c8e0b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('chase_holds',
    sa.Column('invoice_id', sa.String(), nullable=False),
    sa.Column('reason', sa.String(), nullable=False),
    sa.Column('until', sa.Date(), nullable=True),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('invoice_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('chase_holds')
