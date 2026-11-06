"""oauth tables for the hosted MCP server

Revision ID: a9c3e5f7b1d2
Revises: f1a4d7b2c8e0
Create Date: 2026-11-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9c3e5f7b1d2'
down_revision: Union[str, Sequence[str], None] = 'f1a4d7b2c8e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('oauth_clients',
    sa.Column('client_id', sa.String(), nullable=False),
    sa.Column('info', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('client_id')
    )
    op.create_table('oauth_grants',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('link_code', sa.String(), nullable=False),
    sa.Column('client_id', sa.String(), nullable=False),
    sa.Column('client_name', sa.String(), nullable=True),
    sa.Column('redirect_uri', sa.Text(), nullable=False),
    sa.Column('redirect_uri_provided_explicitly', sa.Boolean(), nullable=False),
    sa.Column('state', sa.Text(), nullable=True),
    sa.Column('code_challenge', sa.String(), nullable=False),
    sa.Column('scopes', sa.String(), nullable=False),
    sa.Column('resource', sa.Text(), nullable=True),
    sa.Column('business_id', sa.String(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_oauth_grants_link_code'), 'oauth_grants', ['link_code'], unique=False)
    op.create_table('oauth_tokens',
    sa.Column('token_hash', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('client_id', sa.String(), nullable=False),
    sa.Column('business_id', sa.String(), nullable=False),
    sa.Column('scopes', sa.String(), nullable=False),
    sa.Column('resource', sa.Text(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('code_challenge', sa.String(), nullable=True),
    sa.Column('redirect_uri', sa.Text(), nullable=True),
    sa.Column('redirect_uri_provided_explicitly', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('token_hash')
    )
    op.create_index(op.f('ix_oauth_tokens_business_id'), 'oauth_tokens', ['business_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_oauth_tokens_business_id'), table_name='oauth_tokens')
    op.drop_table('oauth_tokens')
    op.drop_index(op.f('ix_oauth_grants_link_code'), table_name='oauth_grants')
    op.drop_table('oauth_grants')
    op.drop_table('oauth_clients')
