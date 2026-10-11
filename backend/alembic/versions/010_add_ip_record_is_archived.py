"""add ip_record.is_archived

Revision ID: 010
Revises: 009
Create Date: 2026-10-11

The IpRecord model (app/models/base.py, `is_archived = Column(Boolean,
default=False, nullable=False, index=True)`) and the admin archive/unarchive
endpoints (app/api/admin.py PATCH /admin/ip-records/{id}, list filter
`is_archived`) rely on ip_record.is_archived, but no migration ever created
the column. Production only has it because the schema was altered out-of-band
by ``backend/migrate_add_is_archived.py`` against the live database. On a
database built from migrations alone, any SELECT of IpRecord fails with:

    column ip_record.is_archived does not exist

This migration is additive: it adds the NOT NULL BOOLEAN column with a
server-side default of false (backfilling existing rows) and the index the
model expects. Downgrade drops both.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '010'
down_revision: Union[str, Sequence[str], None] = '009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Written idempotently (``IF NOT EXISTS``) on purpose. Production already has
    this column out-of-band: ``backend/migrate_add_is_archived.py`` was run
    against the live (Neon) database (``ALTER TABLE ... ADD COLUMN IF NOT
    EXISTS``) without bumping the Alembic revision, and ``IpRecord.is_archived``
    is selected on every record query. A plain ``op.add_column`` would therefore
    fail during the Render ``preDeployCommand`` with
    ``column "is_archived" of relation "ip_record" already exists``. These
    statements are safe both on a fresh database (column + index are created)
    and on an out-of-band database (both are no-ops), matching
    ``migrate_add_is_archived.py``.
    """
    op.execute(
        "ALTER TABLE ip_record "
        "ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ip_record_is_archived "
        "ON ip_record (is_archived)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_ip_record_is_archived")
    op.execute("ALTER TABLE ip_record DROP COLUMN IF EXISTS is_archived")
