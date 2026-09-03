"""initial_schema

Revision ID: 001
Revises: 
Create Date: 2026-08-28 10:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ENUM as PG_ENUM


# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # Create enums first. create_type=False keeps op.create_table() below from
    # implicitly re-emitting CREATE TYPE for these same named enums (which would
    # fail on a fresh database after the explicit .create() calls here). Generic
    # sa.Enum does not honour create_type, so the Postgres ENUM type is used.
    user_role_enum = PG_ENUM('super_admin', 'faculty', name='user_role_enum', create_type=False)
    user_role_enum.create(op.get_bind(), checkfirst=True)

    ip_type_enum = PG_ENUM('PATENT', 'DESIGN_REGISTRATION', 'UNKNOWN_OTHER', name='ip_type_enum', create_type=False)
    ip_type_enum.create(op.get_bind(), checkfirst=True)

    processing_status_enum = PG_ENUM('PENDING', 'QUEUED', 'PROCESSING', 'AWAITING_REVIEW', 'COMPLETED', 'FAILED', name='processing_status_enum', create_type=False)
    processing_status_enum.create(op.get_bind(), checkfirst=True)

    verification_status_enum = PG_ENUM('UNVERIFIED', 'VERIFICATION_REQUIRED', 'VERIFIED', 'MISMATCH', name='verification_status_enum', create_type=False)
    verification_status_enum.create(op.get_bind(), checkfirst=True)

    association_status_enum = PG_ENUM('PENDING', 'APPROVED', 'REJECTED', 'CLARIFICATION_REQUESTED', 'CANCELLED', name='association_status_enum', create_type=False)
    association_status_enum.create(op.get_bind(), checkfirst=True)

    conflict_status_enum = PG_ENUM('OPEN', 'RESOLVED', 'DISMISSED', name='conflict_status_enum', create_type=False)
    conflict_status_enum.create(op.get_bind(), checkfirst=True)

    # --- Core Tables ---

    # user table
    op.create_table(
        'user',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('email', sa.String(), nullable=False, unique=True, index=True),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('full_name', sa.String(), nullable=False),
        sa.Column('role', user_role_enum, nullable=False, server_default='faculty'),
        sa.Column('faculty_id', sa.String(), unique=True, nullable=True, index=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), onupdate=sa.text('now()')),
    )

    # department table
    op.create_table(
        'department',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False, unique=True, index=True),
        sa.Column('code', sa.String(), unique=True, nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # designation table
    op.create_table(
        'designation',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('title', sa.String(), nullable=False, unique=True, index=True),
        sa.Column('level', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # external_contributor table
    op.create_table(
        'external_contributor',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False, unique=True, index=True),
        sa.Column('organization', sa.String(), nullable=True),
        sa.Column('country', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # rate_limit_state table
    op.create_table(
        'rate_limit_state',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('key', sa.String(), nullable=False, unique=True, index=True),
        sa.Column('count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('reset_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), onupdate=sa.text('now()')),
    )

    # ip_record table
    op.create_table(
        'ip_record',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('ip_type', ip_type_enum, nullable=False, index=True),
        sa.Column('patent_number', sa.String(), unique=True, nullable=True, index=True),
        sa.Column('application_number', sa.String(), unique=True, nullable=True, index=True),
        sa.Column('design_number', sa.String(), unique=True, nullable=True, index=True),
        sa.Column('serial_number', sa.String(), unique=True, nullable=True, index=True),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('patentee', sa.String(), nullable=True),
        sa.Column('applicant', sa.String(), nullable=True),
        sa.Column('published_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('filing_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('grant_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('contributor_name', sa.String(), nullable=True),
        sa.Column('contributor_designation', sa.String(), nullable=True),
        sa.Column('contributor_department', sa.String(), nullable=True),
        sa.Column('contributor_country', sa.String(), nullable=True),
        sa.Column('verification_status', verification_status_enum, nullable=False, server_default='UNVERIFIED', index=True),
        sa.Column('processing_status', processing_status_enum, nullable=False, server_default='PENDING', index=True),
        sa.Column('uploader_id', sa.String(), sa.ForeignKey('user.id'), nullable=False, index=True),
        sa.Column('department_id', sa.String(), sa.ForeignKey('department.id'), nullable=True, index=True),
        sa.Column('designation_id', sa.String(), sa.ForeignKey('designation.id'), nullable=True, index=True),
        sa.Column('evidence', sa.JSON(), nullable=True),
        sa.Column('qr_data', sa.Text(), nullable=True),
        sa.Column('certificate_type', sa.String(), nullable=True),
        sa.Column('source_reference', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), onupdate=sa.text('now()')),
    )

    # ip_contributor table
    op.create_table(
        'ip_contributor',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('ip_record_id', sa.String(), sa.ForeignKey('ip_record.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', sa.String(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('designation', sa.String(), nullable=True),
        sa.Column('department', sa.String(), nullable=True),
        sa.Column('is_external', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('contributor_order', sa.Integer(), nullable=False, server_default=sa.text('0')),
    )

    # ip_file table
    op.create_table(
        'ip_file',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('ip_record_id', sa.String(), sa.ForeignKey('ip_record.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('storage_key', sa.String(), nullable=False, unique=True, index=True),
        sa.Column('original_filename', sa.String(), nullable=False),
        sa.Column('file_extension', sa.String(), nullable=False),
        sa.Column('file_size_bytes', sa.Integer(), nullable=False),
        sa.Column('mime_type', sa.String(), nullable=True),
        sa.Column('fingerprint', sa.String(), nullable=True, index=True),
        sa.Column('page_count', sa.Integer(), nullable=True),
        sa.Column('width_px', sa.Integer(), nullable=True),
        sa.Column('height_px', sa.Integer(), nullable=True),
        sa.Column('upload_status', sa.String(), nullable=False, server_default='PENDING', index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # processing_job table
    op.create_table(
        'processing_job',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('ip_record_id', sa.String(), sa.ForeignKey('ip_record.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('job_type', sa.String(), nullable=False, index=True),
        sa.Column('status', sa.String(), nullable=False, server_default='PENDING', index=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('max_retries', sa.Integer(), nullable=False, server_default=sa.text('3')),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )

    # verification_attempt table
    op.create_table(
        'verification_attempt',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('ip_record_id', sa.String(), sa.ForeignKey('ip_record.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('attempt_number', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('status', verification_status_enum, nullable=False),
        sa.Column('result', sa.Text(), nullable=True),
        sa.Column('evidence', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # association_request table
    op.create_table(
        'association_request',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('requester_id', sa.String(), sa.ForeignKey('user.id'), nullable=False, index=True),
        sa.Column('recipient_id', sa.String(), sa.ForeignKey('user.id'), nullable=True, index=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('status', association_status_enum, nullable=False, server_default='PENDING', index=True),
        sa.Column('response_reason', sa.Text(), nullable=True),
        sa.Column('responder_id', sa.String(), sa.ForeignKey('user.id'), nullable=True, index=True),
        sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('responded_at_timestamp', sa.DateTime(timezone=True), nullable=True),
    )

    # duplicate_case table
    op.create_table(
        'duplicate_case',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('ip_record_id_1', sa.String(), sa.ForeignKey('ip_record.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('ip_record_id_2', sa.String(), sa.ForeignKey('ip_record.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('detection_method', sa.String(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('detected_by', sa.String(), sa.ForeignKey('user.id'), nullable=True, index=True),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('status', conflict_status_enum, nullable=False, server_default='OPEN', index=True),
        sa.Column('kept_record_id', sa.String(), nullable=True, index=True),
        sa.Column('resolved_by', sa.String(), sa.ForeignKey('user.id'), nullable=True, index=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
    )

    # identity_conflict table
    op.create_table(
        'identity_conflict',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id_1', sa.String(), sa.ForeignKey('user.id'), nullable=False, index=True),
        sa.Column('user_id_2', sa.String(), sa.ForeignKey('user.id'), nullable=False, index=True),
        sa.Column('conflict_type', sa.String(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('status', conflict_status_enum, nullable=False, server_default='OPEN', index=True),
        sa.Column('resolved_by', sa.String(), sa.ForeignKey('user.id'), nullable=True, index=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # conflict_case table
    op.create_table(
        'conflict_case',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('ip_record_id', sa.String(), sa.ForeignKey('ip_record.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('conflict_type', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', conflict_status_enum, nullable=False, server_default='OPEN', index=True),
        sa.Column('resolved_by', sa.String(), sa.ForeignKey('user.id'), nullable=True, index=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # notification table
    op.create_table(
        'notification',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), sa.ForeignKey('user.id'), nullable=False, index=True),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('related_entity_type', sa.String(), nullable=True),
        sa.Column('related_entity_id', sa.String(), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # audit_log table
    op.create_table(
        'audit_log',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('actor_id', sa.String(), sa.ForeignKey('user.id'), nullable=True, index=True),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('target_type', sa.String(), nullable=False),
        sa.Column('target_id', sa.String(), nullable=True),
        sa.Column('before_state', sa.JSON(), nullable=True),
        sa.Column('after_state', sa.JSON(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # security_event table
    op.create_table(
        'security_event',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('source_ip', sa.String(), nullable=True),
        sa.Column('user_id', sa.String(), sa.ForeignKey('user.id'), nullable=True, index=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )


def downgrade() -> None:
    """Downgrade schema."""

    # Drop tables in reverse order
    op.drop_table('security_event')
    op.drop_table('audit_log')
    op.drop_table('notification')
    op.drop_table('conflict_case')
    op.drop_table('identity_conflict')
    op.drop_table('duplicate_case')
    op.drop_table('association_request')
    op.drop_table('verification_attempt')
    op.drop_table('processing_job')
    op.drop_table('ip_file')
    op.drop_table('ip_contributor')
    op.drop_table('ip_record')
    op.drop_table('rate_limit_state')
    op.drop_table('external_contributor')
    op.drop_table('designation')
    op.drop_table('department')
    op.drop_table('user')

    # Drop enums
    op.execute("DROP TYPE IF EXISTS conflict_status_enum")
    op.execute("DROP TYPE IF EXISTS association_status_enum")
    op.execute("DROP TYPE IF EXISTS verification_status_enum")
    op.execute("DROP TYPE IF EXISTS processing_status_enum")
    op.execute("DROP TYPE IF EXISTS ip_type_enum")
    op.execute("DROP TYPE IF EXISTS user_role_enum")