"""canonical_data + verification_decision columns

Revision ID: 006
Revises: 52ce3b033131
Create Date: 2026-09-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = '006'
down_revision: Union[str, Sequence[str], None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add canonical_data JSONB column to ip_record
    op.add_column('ip_record', sa.Column('canonical_data', JSONB, nullable=True))
    op.create_index('ix_ip_record_canonical_data', 'ip_record', ['canonical_data'], unique=False, postgresql_using='gin')

    # Add verification_decision JSONB column to master_ip_record
    op.add_column('master_ip_record', sa.Column('verification_decision', JSONB, nullable=True))
    op.create_index('ix_master_ip_record_verification_decision', 'master_ip_record', ['verification_decision'], unique=False, postgresql_using='gin')

    # Add fingerprint_match to duplicate_case for re-upload detection
    op.add_column('duplicate_case', sa.Column('fingerprint_match', sa.Boolean(), nullable=True, server_default=sa.text('false')))
    op.create_index('ix_duplicate_case_fingerprint_match', 'duplicate_case', ['fingerprint_match'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_duplicate_case_fingerprint_match', table_name='duplicate_case')
    op.drop_column('duplicate_case', 'fingerprint_match')

    op.drop_index('ix_master_ip_record_verification_decision', table_name='master_ip_record')
    op.drop_column('master_ip_record', 'verification_decision')

    op.drop_index('ix_ip_record_canonical_data', table_name='ip_record')
    op.drop_column('ip_record', 'canonical_data')