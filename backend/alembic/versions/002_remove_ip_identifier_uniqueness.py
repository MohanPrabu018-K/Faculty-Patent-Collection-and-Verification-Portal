"""remove ip identifier uniqueness

Revision ID: 002
Revises: 001
Create Date: 2026-08-31 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, Sequence[str], None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_ip_record_patent_number', table_name='ip_record')
    op.drop_index('ix_ip_record_design_number', table_name='ip_record')
    op.create_index('ix_ip_record_patent_number', 'ip_record', ['patent_number'], unique=False)
    op.create_index('ix_ip_record_design_number', 'ip_record', ['design_number'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_ip_record_patent_number', table_name='ip_record')
    op.drop_index('ix_ip_record_design_number', table_name='ip_record')
    op.create_index('ix_ip_record_patent_number', 'ip_record', ['patent_number'], unique=True)
    op.create_index('ix_ip_record_design_number', 'ip_record', ['design_number'], unique=True)
