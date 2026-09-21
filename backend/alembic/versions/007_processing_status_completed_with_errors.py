"""add COMPLETED_WITH_ERRORS to processing_status_enum

Revision ID: 007
Revises: f5cfdeecb51b
Create Date: 2026-09-17

The application model (PROCESSING_STATUS_CHOICES in app/models/base.py) and
the frontend "Completed with errors" filter already use COMPLETED_WITH_ERRORS,
but the production PostgreSQL enum was created without it (001 only created
PENDING, QUEUED, PROCESSING, AWAITING_REVIEW, COMPLETED, FAILED). Any query
filtering processing_status=COMPLETED_WITH_ERRORS therefore fails at the
driver level with an invalid-enum-value error, which surfaces in the UI as
"Failed to fetch" on Completed Errors views.

This migration is purely additive: it adds the missing label to the existing
enum. No tables, columns, or existing data are modified. Downgrade is a no-op
because PostgreSQL cannot remove an enum label inside a transaction-safe
downgrade (and existing rows may legitimately carry the value afterwards).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '007'
down_revision: Union[str, Sequence[str], None] = 'f5cfdeecb51b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block, so
    # commit Alembic's open transaction first (known Alembic/PostgreSQL
    # pattern). The version-table update below runs in a fresh transaction.
    bind = op.get_bind()
    bind.execute(sa.text("COMMIT"))
    bind.execute(
        sa.text(
            "ALTER TYPE processing_status_enum "
            "ADD VALUE IF NOT EXISTS 'COMPLETED_WITH_ERRORS'"
        )
    )


def downgrade() -> None:
    """Downgrade schema (no-op: enum labels cannot be safely removed)."""
    pass
