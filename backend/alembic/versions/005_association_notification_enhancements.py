"""association status enum expansion + persistent notification columns

Revision ID: 005
Revises: 52ce3b033131
Create Date: 2026-09-02 04:50:00.000000

Adds the new association workflow states (ACCEPTED, NOT_ME, ADMIN_REVIEW,
EXPIRED) and the ESCALATED conflict state to the existing Postgres enums, plus
the richer notification columns required by the persistent NotificationService.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, Sequence[str], None] = '52ce3b033131'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ASSOCIATION_NEW_VALUES = ("ACCEPTED", "NOT_ME", "ADMIN_REVIEW", "EXPIRED")
_CONFLICT_NEW_VALUES = ("ESCALATED",)


def upgrade() -> None:
    """Add enum values and persistent notification columns."""
    # PostgreSQL supports ADD VALUE IF NOT EXISTS since 12. Neon runs 15/16.
    for value in _ASSOCIATION_NEW_VALUES:
        op.execute(
            f"ALTER TYPE association_status_enum ADD VALUE IF NOT EXISTS '{value}'"
        )
    for value in _CONFLICT_NEW_VALUES:
        op.execute(
            f"ALTER TYPE conflict_status_enum ADD VALUE IF NOT EXISTS '{value}'"
        )

    op.add_column('notification', sa.Column('priority', sa.String(), nullable=True))
    op.add_column('notification', sa.Column('action_url', sa.String(), nullable=True))
    op.add_column('notification', sa.Column('action_label', sa.String(), nullable=True))
    op.add_column('notification', sa.Column('read_at', sa.DateTime(), nullable=True))
    op.add_column('notification', sa.Column('expires_at', sa.DateTime(), nullable=True))
    op.add_column('notification', sa.Column('meta', sa.JSON(), nullable=True))
    op.execute("UPDATE notification SET priority = 'MEDIUM' WHERE priority IS NULL")
    op.alter_column('notification', 'priority', nullable=False, server_default='MEDIUM')

    # Link an association request to the exact IpRecord submission it targets
    # (the master_ip_id column tracks the deduplicated master record, which may
    # not exist yet at request time).
    op.add_column('association_request', sa.Column('ip_record_id', sa.String(), nullable=True))
    op.create_index('ix_association_request_ip_record_id', 'association_request', ['ip_record_id'], unique=False)
    op.create_foreign_key(None, 'association_request', 'ip_record', ['ip_record_id'], ['id'])


def downgrade() -> None:
    """Drop the notification columns added in this revision.

    Postgres does not support removing individual enum values, so the enum
    expansions are intentionally left in place on downgrade.
    """
    op.drop_constraint(None, 'association_request', type_='foreignkey')
    op.drop_index('ix_association_request_ip_record_id', table_name='association_request')
    op.drop_column('association_request', 'ip_record_id')

    op.drop_column('notification', 'meta')
    op.drop_column('notification', 'expires_at')
    op.drop_column('notification', 'read_at')
    op.drop_column('notification', 'action_label')
    op.drop_column('notification', 'action_url')
    op.drop_column('notification', 'priority')
