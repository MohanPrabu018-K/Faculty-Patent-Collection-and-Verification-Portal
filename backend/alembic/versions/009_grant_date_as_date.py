"""grant_date_as_date

Revision ID: 009
Revises: 008
Create Date: 2026-10-07

BUG 7: grant_date must be a proper DATE value, not a timestamp.
Converts ip_record.grant_date and master_ip_record.grant_date from
TIMESTAMP to DATE. The USING clause truncates any stored time component
(production rows hold midnight); the downgrade restores TIMESTAMP.

Non-destructive: no rows deleted, nullable preserved, no default change.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '009'
down_revision: Union[str, Sequence[str], None] = '008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        'ALTER TABLE ip_record ALTER COLUMN grant_date '
        'TYPE DATE USING grant_date::date'
    )
    op.execute(
        'ALTER TABLE master_ip_record ALTER COLUMN grant_date '
        'TYPE DATE USING grant_date::date'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        'ALTER TABLE ip_record ALTER COLUMN grant_date '
        'TYPE TIMESTAMP USING grant_date::timestamp'
    )
    op.execute(
        'ALTER TABLE master_ip_record ALTER COLUMN grant_date '
        'TYPE TIMESTAMP USING grant_date::timestamp'
    )
