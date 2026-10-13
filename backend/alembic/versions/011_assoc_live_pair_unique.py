"""assoc_live_pair_unique

Revision ID: 011
Revises: 010
Create Date: 2026-10-13

A9: database-level backstop for "exactly one live association request per
(record, requester, target) pair". Application code validates first
(human-readable 409 with the live status); this partial unique index makes
the rule unbypassable under concurrent inserts, which the app-level
check-then-insert cannot serialize.

Scope is deliberately PARTIAL:
- Only live (non-terminal) statuses are covered:
  PENDING, CLARIFICATION_REQUESTED, ADMIN_REVIEW, ACCEPTED, APPROVED.
- Terminal rows (REJECTED, NOT_ME, EXPIRED, CANCELLED) are association
  HISTORY and are intentionally allowed to coexist with a newer live row:
  a rejection stays on record until a fresh request is sent and accepted
  (retry/reopen semantics preserved).
- The requester/target alias columns (requesting_faculty_id/requester_id,
  target_faculty_id/recipient_id) are coalesced so legacy rows using either
  pair participate.
- Reverse-direction and cross-master pairs remain guarded at the
  application level (same as the primary POST / duplicate check).

Pre-migration audit on staging (2026-10-13): zero live-pair conflicts.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '011'
down_revision: Union[str, Sequence[str], None] = '010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LIVE_STATUSES = ("PENDING", "CLARIFICATION_REQUESTED", "ADMIN_REVIEW", "ACCEPTED", "APPROVED")


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_assoc_live_pair_per_record
        ON association_request (
            ip_record_id,
            COALESCE(requesting_faculty_id, requester_id),
            COALESCE(target_faculty_id, recipient_id)
        )
        WHERE status IN ('PENDING', 'CLARIFICATION_REQUESTED', 'ADMIN_REVIEW', 'ACCEPTED', 'APPROVED')
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS uq_assoc_live_pair_per_record")
