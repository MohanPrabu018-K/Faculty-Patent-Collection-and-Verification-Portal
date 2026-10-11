"""add hod_admin to user_role_enum

Revision ID: 007a
Revises: 007
Create Date: 2026-10-11

The application model (USER_ROLE_CHOICES in app/models/base.py) and the HOD
workflow use the 'hod_admin' role, but migration 001 created user_role_enum
with only ('super_admin', 'faculty'). No migration ever added 'hod_admin';
production only has it because the type was altered out-of-band. As a result
migration 008 (CREATE UNIQUE INDEX ... WHERE role = 'hod_admin') fails on a
fresh database with:

    invalid input value for enum user_role_enum: "hod_admin"

This migration is purely additive and idempotent: it adds the missing label
before 008 indexes on it. No tables, columns, or existing data are modified.
Downgrade is a no-op because PostgreSQL cannot remove an enum label safely.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '007a'
down_revision: Union[str, Sequence[str], None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ALTER TYPE ... ADD VALUE historically could not run inside a transaction
    # block, so commit Alembic's open transaction first (same pattern as 007).
    bind = op.get_bind()
    bind.execute(sa.text("COMMIT"))
    bind.execute(
        sa.text("ALTER TYPE user_role_enum ADD VALUE IF NOT EXISTS 'hod_admin'")
    )


def downgrade() -> None:
    """Downgrade schema (no-op: enum labels cannot be safely removed)."""
    pass
