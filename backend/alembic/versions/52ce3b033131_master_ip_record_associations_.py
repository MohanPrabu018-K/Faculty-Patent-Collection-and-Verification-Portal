"""master ip record + associations + provenance + history

Revision ID: 52ce3b033131
Revises: 003
Create Date: 2026-09-01 23:42:10.635073
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '52ce3b033131'
down_revision: Union[str, Sequence[str], None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema safely without losing existing rows."""
    # --- New master-record tables ---
    op.create_table(
        'master_ip_record',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('ip_type', postgresql.ENUM('PATENT', 'DESIGN_REGISTRATION', 'UNKNOWN_OTHER', name='ip_type_enum', create_type=False), nullable=False),
        sa.Column('patent_number', sa.String(), nullable=True),
        sa.Column('application_number', sa.String(), nullable=True),
        sa.Column('publication_number', sa.String(), nullable=True),
        sa.Column('design_number', sa.String(), nullable=True),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('filing_date', sa.DateTime(), nullable=True),
        sa.Column('publication_date', sa.DateTime(), nullable=True),
        sa.Column('registration_date', sa.DateTime(), nullable=True),
        sa.Column('grant_date', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='ACTIVE'),
        sa.Column('official_source', sa.String(), nullable=True),
        sa.Column('official_source_url', sa.String(), nullable=True),
        sa.Column('official_verification_status', sa.String(), nullable=True),
        sa.Column('workflow_state', sa.String(), nullable=False, server_default='UPLOADED'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    for col in ('ip_type', 'application_number', 'design_number', 'patent_number', 'publication_number', 'status', 'workflow_state'):
        op.create_index(f'ix_master_ip_record_{col}', 'master_ip_record', [col], unique=False)

    op.create_table(
        'master_ip_contributor',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('master_ip_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('contributor_type', sa.String(), nullable=False, server_default='UNKNOWN'),
        sa.Column('matched_faculty_id', sa.String(), nullable=True),
        sa.Column('author_position', sa.Integer(), nullable=True),
        sa.Column('match_confidence', sa.Float(), nullable=True),
        sa.Column('match_status', sa.String(), nullable=False, server_default='VERIFICATION_REQUIRED'),
        sa.Column('institution', sa.String(), nullable=True),
        sa.Column('source', sa.String(), nullable=False, server_default='CERTIFICATE_OCR'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['master_ip_id'], ['master_ip_record.id']),
        sa.ForeignKeyConstraint(['matched_faculty_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    for col in ('master_ip_id', 'contributor_type', 'matched_faculty_id'):
        op.create_index(f'ix_master_ip_contributor_{col}', 'master_ip_contributor', [col], unique=False)

    op.create_table(
        'faculty_ip_association',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('master_ip_id', sa.String(), nullable=False),
        sa.Column('faculty_id', sa.String(), nullable=False),
        sa.Column('contributor_id', sa.String(), nullable=True),
        sa.Column('author_position', sa.Integer(), nullable=True),
        sa.Column('association_status', sa.String(), nullable=False, server_default='PENDING'),
        sa.Column('verification_status', sa.String(), nullable=False, server_default='UNVERIFIED'),
        sa.Column('association_source', sa.String(), nullable=False, server_default='UPLOADER'),
        sa.Column('verified_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['master_ip_id'], ['master_ip_record.id']),
        sa.ForeignKeyConstraint(['faculty_id'], ['user.id']),
        sa.ForeignKeyConstraint(['contributor_id'], ['master_ip_contributor.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    for col in ('master_ip_id', 'faculty_id', 'contributor_id', 'association_status', 'verification_status'):
        op.create_index(f'ix_faculty_ip_association_{col}', 'faculty_ip_association', [col], unique=False)

    op.create_table(
        'master_verification_attempt',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('master_ip_id', sa.String(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('attempted_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('response', sa.JSON(), nullable=True),
        sa.Column('extracted_data', sa.JSON(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['master_ip_id'], ['master_ip_record.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_master_verification_attempt_master_ip_id', 'master_verification_attempt', ['master_ip_id'], unique=False)

    op.create_table(
        'faculty_profile_snapshot',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('faculty_id', sa.String(), nullable=False),
        sa.Column('master_ip_id', sa.String(), nullable=False),
        sa.Column('full_name', sa.String(), nullable=True),
        sa.Column('department_name', sa.String(), nullable=True),
        sa.Column('designation_name', sa.String(), nullable=True),
        sa.Column('captured_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['faculty_id'], ['user.id']),
        sa.ForeignKeyConstraint(['master_ip_id'], ['master_ip_record.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    for col in ('faculty_id', 'master_ip_id'):
        op.create_index(f'ix_faculty_profile_snapshot_{col}', 'faculty_profile_snapshot', [col], unique=False)

    op.create_table(
        'field_provenance',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('ip_record_id', sa.String(), nullable=True),
        sa.Column('master_ip_id', sa.String(), nullable=True),
        sa.Column('field_name', sa.String(), nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('source', sa.String(), nullable=False, server_default='UNKNOWN'),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='PENDING'),
        sa.Column('certificate_value', sa.Text(), nullable=True),
        sa.Column('official_value', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['ip_record_id'], ['ip_record.id']),
        sa.ForeignKeyConstraint(['master_ip_id'], ['master_ip_record.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    for col in ('ip_record_id', 'master_ip_id', 'field_name', 'source', 'status'):
        op.create_index(f'ix_field_provenance_{col}', 'field_provenance', [col], unique=False)

    # --- user: faculty master profile ---
    op.add_column('user', sa.Column('official_email', sa.String(), nullable=True))
    op.add_column('user', sa.Column('department_id', sa.String(), nullable=True))
    op.add_column('user', sa.Column('designation_id', sa.String(), nullable=True))
    op.add_column('user', sa.Column('joining_date', sa.DateTime(), nullable=True))
    op.add_column('user', sa.Column('status', sa.String(), nullable=True))
    op.execute("UPDATE \"user\" SET status = 'active' WHERE status IS NULL")
    op.alter_column('user', 'status', nullable=False, server_default='active')
    op.create_index('ix_user_department_id', 'user', ['department_id'], unique=False)
    op.create_index('ix_user_designation_id', 'user', ['designation_id'], unique=False)
    op.create_foreign_key(None, 'user', 'department', ['department_id'], ['id'])
    op.create_foreign_key(None, 'user', 'designation', ['designation_id'], ['id'])

    # --- department / designation status ---
    op.add_column('department', sa.Column('status', sa.String(), nullable=True))
    op.execute("UPDATE department SET status = 'active' WHERE status IS NULL")
    op.alter_column('department', 'status', nullable=False, server_default='active')

    op.add_column('designation', sa.Column('name', sa.String(), nullable=True))
    op.add_column('designation', sa.Column('status', sa.String(), nullable=True))
    op.execute("UPDATE designation SET status = 'active' WHERE status IS NULL")
    op.alter_column('designation', 'status', nullable=False, server_default='active')

    # --- ip_record: master linkage + official fields ---
    op.add_column('ip_record', sa.Column('master_ip_id', sa.String(), nullable=True))
    op.add_column('ip_record', sa.Column('publication_number', sa.String(), nullable=True))
    op.add_column('ip_record', sa.Column('publication_date', sa.DateTime(), nullable=True))
    op.add_column('ip_record', sa.Column('registration_date', sa.DateTime(), nullable=True))
    op.add_column('ip_record', sa.Column('workflow_state', sa.String(), nullable=True))
    op.add_column('ip_record', sa.Column('official_source', sa.String(), nullable=True))
    op.add_column('ip_record', sa.Column('official_source_url', sa.String(), nullable=True))
    op.add_column('ip_record', sa.Column('official_verification_status', sa.String(), nullable=True))
    op.add_column('ip_record', sa.Column('historical_department_id', sa.String(), nullable=True))
    op.add_column('ip_record', sa.Column('historical_department_name', sa.String(), nullable=True))
    op.add_column('ip_record', sa.Column('document_type', sa.String(), nullable=True))
    op.execute("UPDATE ip_record SET workflow_state = 'UPLOADED' WHERE workflow_state IS NULL")
    op.execute("UPDATE ip_record SET document_type = 'CERTIFICATE' WHERE document_type IS NULL")
    op.alter_column('ip_record', 'workflow_state', nullable=False, server_default='UPLOADED')
    op.alter_column('ip_record', 'document_type', nullable=False, server_default='CERTIFICATE')

    # application_number must not be globally unique (dedupe layer handles this)
    op.drop_index('ix_ip_record_application_number', table_name='ip_record')
    op.create_index('ix_ip_record_application_number', 'ip_record', ['application_number'], unique=False)
    op.create_index('ix_ip_record_master_ip_id', 'ip_record', ['master_ip_id'], unique=False)
    op.create_index('ix_ip_record_publication_number', 'ip_record', ['publication_number'], unique=False)
    op.create_index('ix_ip_record_workflow_state', 'ip_record', ['workflow_state'], unique=False)
    op.create_foreign_key(None, 'ip_record', 'master_ip_record', ['master_ip_id'], ['id'])
    op.create_foreign_key(None, 'ip_record', 'department', ['historical_department_id'], ['id'])

    # --- ip_contributor: classification fields ---
    op.add_column('ip_contributor', sa.Column('institution', sa.String(), nullable=True))
    op.add_column('ip_contributor', sa.Column('contributor_type', sa.String(), nullable=True))
    op.add_column('ip_contributor', sa.Column('author_position', sa.Integer(), nullable=True))
    op.add_column('ip_contributor', sa.Column('match_confidence', sa.Float(), nullable=True))
    op.add_column('ip_contributor', sa.Column('match_status', sa.String(), nullable=True))
    op.add_column('ip_contributor', sa.Column('source', sa.String(), nullable=True))
    op.execute("UPDATE ip_contributor SET contributor_type = 'UNKNOWN' WHERE contributor_type IS NULL")
    op.execute("UPDATE ip_contributor SET match_status = 'VERIFICATION_REQUIRED' WHERE match_status IS NULL")
    op.execute("UPDATE ip_contributor SET source = 'CERTIFICATE_OCR' WHERE source IS NULL")
    op.alter_column('ip_contributor', 'contributor_type', nullable=False, server_default='UNKNOWN')
    op.alter_column('ip_contributor', 'match_status', nullable=False, server_default='VERIFICATION_REQUIRED')
    op.alter_column('ip_contributor', 'source', nullable=False, server_default='CERTIFICATE_OCR')
    op.create_index('ix_ip_contributor_contributor_type', 'ip_contributor', ['contributor_type'], unique=False)

    # --- ip_file: master linkage + document type ---
    op.add_column('ip_file', sa.Column('master_ip_id', sa.String(), nullable=True))
    op.add_column('ip_file', sa.Column('uploaded_by', sa.String(), nullable=True))
    op.add_column('ip_file', sa.Column('document_type', sa.String(), nullable=True))
    op.execute("UPDATE ip_file SET document_type = 'CERTIFICATE' WHERE document_type IS NULL")
    op.alter_column('ip_file', 'document_type', nullable=False, server_default='CERTIFICATE')
    op.create_index('ix_ip_file_master_ip_id', 'ip_file', ['master_ip_id'], unique=False)
    op.create_index('ix_ip_file_uploaded_by', 'ip_file', ['uploaded_by'], unique=False)
    op.create_index('ix_ip_file_document_type', 'ip_file', ['document_type'], unique=False)
    op.create_foreign_key(None, 'ip_file', 'master_ip_record', ['master_ip_id'], ['id'])
    op.create_foreign_key(None, 'ip_file', 'user', ['uploaded_by'], ['id'])

    # --- association_request: full workflow ---
    op.add_column('association_request', sa.Column('master_ip_id', sa.String(), nullable=True))
    op.add_column('association_request', sa.Column('contributor_id', sa.String(), nullable=True))
    op.add_column('association_request', sa.Column('requesting_faculty_id', sa.String(), nullable=True))
    op.add_column('association_request', sa.Column('target_faculty_id', sa.String(), nullable=True))
    op.add_column('association_request', sa.Column('message', sa.Text(), nullable=True))
    op.add_column('association_request', sa.Column('clarification_message', sa.Text(), nullable=True))
    op.add_column('association_request', sa.Column('reminder_sent_at', sa.DateTime(), nullable=True))
    op.alter_column('association_request', 'requester_id', existing_type=sa.VARCHAR(), nullable=True)
    op.create_index('ix_association_request_master_ip_id', 'association_request', ['master_ip_id'], unique=False)
    op.create_index('ix_association_request_contributor_id', 'association_request', ['contributor_id'], unique=False)
    op.create_index('ix_association_request_requesting_faculty_id', 'association_request', ['requesting_faculty_id'], unique=False)
    op.create_index('ix_association_request_target_faculty_id', 'association_request', ['target_faculty_id'], unique=False)
    op.create_foreign_key(None, 'association_request', 'master_ip_record', ['master_ip_id'], ['id'])
    op.create_foreign_key(None, 'association_request', 'master_ip_contributor', ['contributor_id'], ['id'])
    op.create_foreign_key(None, 'association_request', 'user', ['requesting_faculty_id'], ['id'])
    op.create_foreign_key(None, 'association_request', 'user', ['target_faculty_id'], ['id'])

    # --- conflict_case: provenance + severity + assignment ---
    op.add_column('conflict_case', sa.Column('master_ip_id', sa.String(), nullable=True))
    op.add_column('conflict_case', sa.Column('field_name', sa.String(), nullable=True))
    op.add_column('conflict_case', sa.Column('detected_value', sa.Text(), nullable=True))
    op.add_column('conflict_case', sa.Column('expected_value', sa.Text(), nullable=True))
    op.add_column('conflict_case', sa.Column('source_a', sa.String(), nullable=True))
    op.add_column('conflict_case', sa.Column('source_b', sa.String(), nullable=True))
    op.add_column('conflict_case', sa.Column('severity', sa.String(), nullable=True))
    op.add_column('conflict_case', sa.Column('assigned_to', sa.String(), nullable=True))
    op.add_column('conflict_case', sa.Column('resolution', sa.Text(), nullable=True))
    op.alter_column('conflict_case', 'ip_record_id', existing_type=sa.VARCHAR(), nullable=True)
    op.execute("UPDATE conflict_case SET severity = 'MEDIUM' WHERE severity IS NULL")
    op.alter_column('conflict_case', 'severity', nullable=False, server_default='MEDIUM')
    op.create_index('ix_conflict_case_master_ip_id', 'conflict_case', ['master_ip_id'], unique=False)
    op.create_index('ix_conflict_case_severity', 'conflict_case', ['severity'], unique=False)
    op.create_index('ix_conflict_case_assigned_to', 'conflict_case', ['assigned_to'], unique=False)
    op.create_foreign_key(None, 'conflict_case', 'master_ip_record', ['master_ip_id'], ['id'])
    op.create_foreign_key(None, 'conflict_case', 'user', ['assigned_to'], ['id'])

    # --- audit_log: persistent rich fields ---
    op.add_column('audit_log', sa.Column('actor_role', sa.String(), nullable=True))
    op.add_column('audit_log', sa.Column('entity_type', sa.String(), nullable=True))
    op.add_column('audit_log', sa.Column('entity_id', sa.String(), nullable=True))
    op.add_column('audit_log', sa.Column('previous_value', sa.JSON(), nullable=True))
    op.add_column('audit_log', sa.Column('new_value', sa.JSON(), nullable=True))
    op.add_column('audit_log', sa.Column('extra', sa.JSON(), nullable=True))
    op.add_column('audit_log', sa.Column('ip_address', sa.String(), nullable=True))
    op.add_column('audit_log', sa.Column('reason', sa.Text(), nullable=True))
    op.alter_column('audit_log', 'target_type', existing_type=sa.VARCHAR(), nullable=True)
    op.create_index('ix_audit_log_entity_type', 'audit_log', ['entity_type'], unique=False)
    op.create_index('ix_audit_log_entity_id', 'audit_log', ['entity_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_audit_log_entity_id', table_name='audit_log')
    op.drop_index('ix_audit_log_entity_type', table_name='audit_log')
    op.drop_column('audit_log', 'reason')
    op.drop_column('audit_log', 'ip_address')
    op.drop_column('audit_log', 'extra')
    op.drop_column('audit_log', 'new_value')
    op.drop_column('audit_log', 'previous_value')
    op.drop_column('audit_log', 'entity_id')
    op.drop_column('audit_log', 'entity_type')
    op.drop_column('audit_log', 'actor_role')

    op.drop_constraint(None, 'conflict_case', type_='foreignkey')
    op.drop_constraint(None, 'conflict_case', type_='foreignkey')
    op.drop_index('ix_conflict_case_assigned_to', table_name='conflict_case')
    op.drop_index('ix_conflict_case_severity', table_name='conflict_case')
    op.drop_index('ix_conflict_case_master_ip_id', table_name='conflict_case')
    op.drop_column('conflict_case', 'resolution')
    op.drop_column('conflict_case', 'assigned_to')
    op.drop_column('conflict_case', 'severity')
    op.drop_column('conflict_case', 'source_b')
    op.drop_column('conflict_case', 'source_a')
    op.drop_column('conflict_case', 'expected_value')
    op.drop_column('conflict_case', 'detected_value')
    op.drop_column('conflict_case', 'field_name')
    op.drop_column('conflict_case', 'master_ip_id')

    op.drop_constraint(None, 'association_request', type_='foreignkey')
    op.drop_constraint(None, 'association_request', type_='foreignkey')
    op.drop_constraint(None, 'association_request', type_='foreignkey')
    op.drop_constraint(None, 'association_request', type_='foreignkey')
    op.drop_index('ix_association_request_target_faculty_id', table_name='association_request')
    op.drop_index('ix_association_request_requesting_faculty_id', table_name='association_request')
    op.drop_index('ix_association_request_contributor_id', table_name='association_request')
    op.drop_index('ix_association_request_master_ip_id', table_name='association_request')
    op.drop_column('association_request', 'reminder_sent_at')
    op.drop_column('association_request', 'clarification_message')
    op.drop_column('association_request', 'message')
    op.drop_column('association_request', 'target_faculty_id')
    op.drop_column('association_request', 'requesting_faculty_id')
    op.drop_column('association_request', 'contributor_id')
    op.drop_column('association_request', 'master_ip_id')

    op.drop_constraint(None, 'ip_file', type_='foreignkey')
    op.drop_constraint(None, 'ip_file', type_='foreignkey')
    op.drop_index('ix_ip_file_document_type', table_name='ip_file')
    op.drop_index('ix_ip_file_uploaded_by', table_name='ip_file')
    op.drop_index('ix_ip_file_master_ip_id', table_name='ip_file')
    op.drop_column('ip_file', 'document_type')
    op.drop_column('ip_file', 'uploaded_by')
    op.drop_column('ip_file', 'master_ip_id')

    op.drop_index('ix_ip_contributor_contributor_type', table_name='ip_contributor')
    op.drop_column('ip_contributor', 'source')
    op.drop_column('ip_contributor', 'match_status')
    op.drop_column('ip_contributor', 'match_confidence')
    op.drop_column('ip_contributor', 'author_position')
    op.drop_column('ip_contributor', 'contributor_type')
    op.drop_column('ip_contributor', 'institution')

    op.drop_constraint(None, 'ip_record', type_='foreignkey')
    op.drop_constraint(None, 'ip_record', type_='foreignkey')
    op.drop_index('ix_ip_record_workflow_state', table_name='ip_record')
    op.drop_index('ix_ip_record_publication_number', table_name='ip_record')
    op.drop_index('ix_ip_record_master_ip_id', table_name='ip_record')
    op.drop_index('ix_ip_record_application_number', table_name='ip_record')
    op.create_index('ix_ip_record_application_number', 'ip_record', ['application_number'], unique=True)
    op.drop_column('ip_record', 'document_type')
    op.drop_column('ip_record', 'historical_department_name')
    op.drop_column('ip_record', 'historical_department_id')
    op.drop_column('ip_record', 'official_verification_status')
    op.drop_column('ip_record', 'official_source_url')
    op.drop_column('ip_record', 'official_source')
    op.drop_column('ip_record', 'workflow_state')
    op.drop_column('ip_record', 'registration_date')
    op.drop_column('ip_record', 'publication_date')
    op.drop_column('ip_record', 'publication_number')
    op.drop_column('ip_record', 'master_ip_id')

    op.drop_column('designation', 'status')
    op.drop_column('designation', 'name')
    op.drop_column('department', 'status')

    op.drop_constraint(None, 'user', type_='foreignkey')
    op.drop_constraint(None, 'user', type_='foreignkey')
    op.drop_index('ix_user_designation_id', table_name='user')
    op.drop_index('ix_user_department_id', table_name='user')
    op.drop_column('user', 'status')
    op.drop_column('user', 'joining_date')
    op.drop_column('user', 'designation_id')
    op.drop_column('user', 'department_id')
    op.drop_column('user', 'official_email')

    op.drop_index('ix_field_provenance_status', table_name='field_provenance')
    op.drop_index('ix_field_provenance_source', table_name='field_provenance')
    op.drop_index('ix_field_provenance_field_name', table_name='field_provenance')
    op.drop_index('ix_field_provenance_master_ip_id', table_name='field_provenance')
    op.drop_index('ix_field_provenance_ip_record_id', table_name='field_provenance')
    op.drop_table('field_provenance')

    op.drop_index('ix_faculty_profile_snapshot_master_ip_id', table_name='faculty_profile_snapshot')
    op.drop_index('ix_faculty_profile_snapshot_faculty_id', table_name='faculty_profile_snapshot')
    op.drop_table('faculty_profile_snapshot')

    op.drop_index('ix_master_verification_attempt_master_ip_id', table_name='master_verification_attempt')
    op.drop_table('master_verification_attempt')

    op.drop_index('ix_faculty_ip_association_verification_status', table_name='faculty_ip_association')
    op.drop_index('ix_faculty_ip_association_association_status', table_name='faculty_ip_association')
    op.drop_index('ix_faculty_ip_association_contributor_id', table_name='faculty_ip_association')
    op.drop_index('ix_faculty_ip_association_faculty_id', table_name='faculty_ip_association')
    op.drop_index('ix_faculty_ip_association_master_ip_id', table_name='faculty_ip_association')
    op.drop_table('faculty_ip_association')

    op.drop_index('ix_master_ip_contributor_matched_faculty_id', table_name='master_ip_contributor')
    op.drop_index('ix_master_ip_contributor_contributor_type', table_name='master_ip_contributor')
    op.drop_index('ix_master_ip_contributor_master_ip_id', table_name='master_ip_contributor')
    op.drop_table('master_ip_contributor')

    op.drop_index('ix_master_ip_record_workflow_state', table_name='master_ip_record')
    op.drop_index('ix_master_ip_record_status', table_name='master_ip_record')
    op.drop_index('ix_master_ip_record_publication_number', table_name='master_ip_record')
    op.drop_index('ix_master_ip_record_patent_number', table_name='master_ip_record')
    op.drop_index('ix_master_ip_record_design_number', table_name='master_ip_record')
    op.drop_index('ix_master_ip_record_application_number', table_name='master_ip_record')
    op.drop_index('ix_master_ip_record_ip_type', table_name='master_ip_record')
    op.drop_table('master_ip_record')
