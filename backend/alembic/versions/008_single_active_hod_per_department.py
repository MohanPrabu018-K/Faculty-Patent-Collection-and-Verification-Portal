"""single_active_hod_per_department

Revision ID: 008
Revises: 007
Create Date: 2026-10-06

Item 7: database-level backstop for "only one ACTIVE HOD per department".
Application code validates first (human-readable 409); this partial unique
index makes the rule unbypassable even if API validation is skipped.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '008'
down_revision: Union[str, Sequence[str], None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_active_hod_per_department
        ON "user" (department_id)
        WHERE role = 'hod_admin' AND is_active IS TRUE AND department_id IS NOT NULL
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS uq_active_hod_per_department")
