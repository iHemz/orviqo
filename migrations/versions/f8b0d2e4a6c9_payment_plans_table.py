"""payment_plans table: debts paid in instalments

Revision ID: f8b0d2e4a6c9
Revises: e5a7c9b1d3f6
Create Date: 2026-11-06 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8b0d2e4a6c9'
down_revision: Union[str, Sequence[str], None] = 'e5a7c9b1d3f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('payment_plans',
    sa.Column('invoice_id', sa.String(), nullable=False),
    sa.Column('amount_ngn', sa.Integer(), nullable=False),
    sa.Column('every', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('invoice_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('payment_plans')
