"""add_certificate_date

Revision ID: 012
Revises: 011
Create Date: 2026-10-19

Adds certificate_date as a calendar DATE to ip_record and master_ip_record.

Semantics:
- Represents the certificate issue date extracted from patent and design certificates
  (e.g., 03/05/2024 for design registration certificates).
- Preserved as a distinct first-class field.
- NOT assigned to grant_date or published_date.
- Stored as calendar DATE (never timestamp with timezone).
- Nullable for backward compatibility with existing records.
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '012'
down_revision: Union[str, Sequence[str], None] = '011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'ip_record',
        sa.Column('certificate_date', sa.Date(), nullable=True)
    )
    op.add_column(
        'master_ip_record',
        sa.Column('certificate_date', sa.Date(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('master_ip_record', 'certificate_date')
    op.drop_column('ip_record', 'certificate_date')
