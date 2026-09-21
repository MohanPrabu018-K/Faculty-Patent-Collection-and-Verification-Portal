"""add_expires_at_to_association_request

Revision ID: f5cfdeecb51b
Revises: 006
Create Date: 2026-09-07 13:28:46.270164

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f5cfdeecb51b'
down_revision: Union[str, Sequence[str], None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add expires_at column to association_request table
    op.add_column('association_request', sa.Column('expires_at', sa.DateTime(), nullable=True))
    # Create index for efficient expiry queries
    op.create_index('ix_association_request_expires_at', 'association_request', ['expires_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_association_request_expires_at', table_name='association_request')
    op.drop_column('association_request', 'expires_at')