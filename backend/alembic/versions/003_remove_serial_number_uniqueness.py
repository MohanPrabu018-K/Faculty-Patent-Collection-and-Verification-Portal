"""remove serial number uniqueness

Revision ID: 003
Revises: 002
Create Date: 2026-09-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, Sequence[str], None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_ip_record_serial_number", table_name="ip_record")
    op.create_index("ix_ip_record_serial_number", "ip_record", ["serial_number"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ip_record_serial_number", table_name="ip_record")
    op.create_index("ix_ip_record_serial_number", "ip_record", ["serial_number"], unique=True)
