import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utcnow() -> datetime:
    """Return timezone-naive UTC datetime."""
    from datetime import datetime, UTC
    return datetime.now(UTC).replace(tzinfo=None)


# --- Simple String Enums (no auto-inheritance issues) ---

IP_TYPE_CHOICES = ("PATENT", "DESIGN_REGISTRATION", "UNKNOWN_OTHER")
PROCESSING_STATUS_CHOICES = ("PENDING", "QUEUED", "PROCESSING", "AWAITING_REVIEW", "COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED")
VERIFICATION_STATUS_CHOICES = ("UNVERIFIED", "VERIFICATION_REQUIRED", "VERIFIED", "MISMATCH")
ASSOCIATION_STATUS_CHOICES = ("PENDING", "ACCEPTED", "APPROVED", "REJECTED", "NOT_ME", "CLARIFICATION_REQUESTED", "ADMIN_REVIEW", "EXPIRED", "CANCELLED")
CONFLICT_STATUS_CHOICES = ("OPEN", "RESOLVED", "DISMISSED", "ESCALATED")
USER_ROLE_CHOICES = ("super_admin", "hod_admin", "faculty")

WORKFLOW_STATE_CHOICES = (
    "UPLOADED",
    "PROCESSING",
    "OCR_COMPLETED",
    "QR_DETECTED",
    "IDENTIFIER_FOUND",
    "VERIFICATION_PENDING",
    "VERIFICATION_REQUIRED",
    "EXTERNAL_VERIFICATION_FAILURE",
    "DATA_CONFLICT",
    "IDENTITY_REVIEW",
    "CONTRIBUTOR_REVIEW",
    "FACULTY_APPROVAL_PENDING",
    "DUPLICATE_REVIEW",
    "NEEDS_REVIEW",
    "VERIFIED",
    "REJECTED",
    "FAILED",
)

CONTRIBUTOR_TYPE_CHOICES = ("INTERNAL_FACULTY", "EXTERNAL", "UNKNOWN")
DOCUMENT_TYPE_CHOICES = (
    "CERTIFICATE",
    "GRANT_DOCUMENT",
    "PUBLICATION_DOCUMENT",
    "REGISTRATION_DOCUMENT",
    "SUPPORTING_DOCUMENT",
    "SUPPORTING_IMAGE",
    "UNKNOWN",
)
FIELD_SOURCE_CHOICES = (
    "CERTIFICATE_OCR",
    "QR_CODE",
    "OFFICIAL_SOURCE",
    "FACULTY_PROFILE",
    "FACULTY_PROFILE_DERIVED",
    "FACULTY_CONFIRMED",
    "ADMIN_CONFIRMED",
    "SYSTEM_DERIVED",
    "NEEDS_VERIFICATION",
    "UNKNOWN",
)
FIELD_STATUS_CHOICES = ("PENDING", "CONFIRMED", "CONFLICT", "NEEDS_VERIFICATION")
MATCH_STATUS_CHOICES = ("SUGGESTED", "CONFIRMED", "VERIFICATION_REQUIRED", "NO_MATCH")


def ip_type_enum():
    """Return SQLAlchemy IpTypeEnum class."""
    return SqlEnum(*IP_TYPE_CHOICES, name="ip_type_enum")


def processing_status_enum():
    """Return SQLAlchemy ProcessingStatusEnum class."""
    return SqlEnum(*PROCESSING_STATUS_CHOICES, name="processing_status_enum")


def verification_status_enum():
    """Return SQLAlchemy VerificationStatusEnum class."""
    return SqlEnum(*VERIFICATION_STATUS_CHOICES, name="verification_status_enum")


def association_status_enum():
    """Return SQLAlchemy AssociationStatusEnum class."""
    return SqlEnum(*ASSOCIATION_STATUS_CHOICES, name="association_status_enum")


def conflict_status_enum():
    """Return SQLAlchemy ConflictStatusEnum class."""
    return SqlEnum(*CONFLICT_STATUS_CHOICES, name="conflict_status_enum")


def user_role_enum():
    """Return SQLAlchemy UserRoleEnum class."""
    return SqlEnum(*USER_ROLE_CHOICES, name="user_role_enum")


# --- Core Entities ---


class User(Base):
    __tablename__ = "user"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, nullable=False, index=True)
    official_email = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(user_role_enum(), default="faculty", nullable=False)
    faculty_id = Column(String, unique=True, nullable=True, index=True)
    department_id = Column(String, ForeignKey("department.id"), nullable=True, index=True)
    designation_id = Column(String, ForeignKey("designation.id"), nullable=True, index=True)
    joining_date = Column(DateTime, nullable=True)
    status = Column(String, default="active", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: utcnow(), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: utcnow(),
        onupdate=lambda: utcnow(),
        nullable=False,
    )

    # Relationships
    department = relationship("Department", foreign_keys=[department_id], back_populates="users")
    designation = relationship("Designation", foreign_keys=[designation_id], back_populates="users")
    ip_contributions = relationship("IpContributor", back_populates="user")
    created_ip_records = relationship("IpRecord", back_populates="uploader")
    faculty_ip_associations = relationship("FacultyIpAssociation", back_populates="faculty")


class Department(Base):
    __tablename__ = "department"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True, nullable=False, index=True)
    code = Column(String, unique=True, nullable=True)
    status = Column(String, default="active", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: utcnow(), nullable=False)

    # Relationships
    ip_records = relationship("IpRecord", foreign_keys="IpRecord.department_id", back_populates="department")
    historical_ip_records = relationship("IpRecord", foreign_keys="IpRecord.historical_department_id")
    users = relationship("User", foreign_keys="User.department_id")


class Designation(Base):
    __tablename__ = "designation"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=True)
    level = Column(String, nullable=True)
    status = Column(String, default="active", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: utcnow(), nullable=False)

    # Relationships
    ip_records = relationship("IpRecord", foreign_keys="IpRecord.designation_id", back_populates="designation")
    users = relationship("User", foreign_keys="User.designation_id")


# --- IP Record System ---


class IpRecord(Base):
    __tablename__ = "ip_record"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    master_ip_id = Column(String, ForeignKey("master_ip_record.id"), nullable=True, index=True)
    ip_type = Column(ip_type_enum(), nullable=False, index=True)

    # Identifier fields - different per type (NOT globally unique; duplicate
    # detection is performed by the deduplication layer, not the schema)
    patent_number = Column(String, nullable=True, index=True)
    application_number = Column(String, nullable=True, index=True)
    publication_number = Column(String, nullable=True, index=True)
    design_number = Column(String, nullable=True, index=True)
    serial_number = Column(String, nullable=True, index=True)

    # Metadata
    title = Column(Text, nullable=True)
    patentee = Column(String, nullable=True)
    applicant = Column(String, nullable=True)
    published_date = Column(DateTime, nullable=True)
    publication_date = Column(DateTime, nullable=True)
    filing_date = Column(DateTime, nullable=True)
    registration_date = Column(DateTime, nullable=True)
    grant_date = Column(DateTime, nullable=True)

    # Contributor info
    contributor_name = Column(String, nullable=True)
    contributor_designation = Column(String, nullable=True)
    contributor_department = Column(String, nullable=True)
    contributor_country = Column(String, nullable=True)

    # Verification & Status
    verification_status = Column(verification_status_enum(), default="UNVERIFIED", nullable=False, index=True)
    processing_status = Column(processing_status_enum(), default="PENDING", nullable=False, index=True)
    workflow_state = Column(String, default="UPLOADED", nullable=False, index=True)

    # Archive flag (A5: admin can archive/unarchive records)
    is_archived = Column(Boolean, default=False, nullable=False, index=True)

    # Official source linkage
    official_source = Column(String, nullable=True)
    official_source_url = Column(String, nullable=True)
    official_verification_status = Column(String, nullable=True)

    # Ownership
    uploader_id = Column(String, ForeignKey("user.id"), nullable=False, index=True)
    department_id = Column(String, ForeignKey("department.id"), nullable=True, index=True)
    designation_id = Column(String, ForeignKey("designation.id"), nullable=True, index=True)

    # Historical department snapshot (preserved even if faculty changes dept)
    historical_department_id = Column(String, ForeignKey("department.id"), nullable=True)
    historical_department_name = Column(String, nullable=True)

    # Evidence & Metadata
    evidence = Column(JSON, nullable=True, default=lambda: {})
    qr_data = Column(Text, nullable=True)
    certificate_type = Column(String, nullable=True)
    source_reference = Column(String, nullable=True)
    document_type = Column(String, default="CERTIFICATE", nullable=False)

    # Canonical structured data (scalar fields, separate from evidence)
    canonical_data = Column(JSON, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=lambda: utcnow(), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: utcnow(),
        onupdate=lambda: utcnow(),
        nullable=False,
    )

    # Relationships
    master_ip = relationship("MasterIpRecord", back_populates="ip_records")
    uploader = relationship("User", back_populates="created_ip_records")
    department = relationship("Department", foreign_keys=[department_id], back_populates="ip_records")
    designation = relationship("Designation", foreign_keys=[designation_id], back_populates="ip_records")
    historical_department = relationship("Department", foreign_keys=[historical_department_id], back_populates="historical_ip_records")
    contributors = relationship("IpContributor", back_populates="ip_record", cascade="all, delete-orphan")
    files = relationship("IpFile", back_populates="ip_record", cascade="all, delete-orphan")
    processing_jobs = relationship("ProcessingJob", back_populates="ip_record", cascade="all, delete-orphan")
    verification_attempts = relationship(
        "VerificationAttempt", back_populates="ip_record", cascade="all, delete-orphan"
    )
    field_provenance = relationship("FieldProvenance", back_populates="ip_record", cascade="all, delete-orphan")
    duplicate_cases_1 = relationship(
        "DuplicateCase",
        foreign_keys="DuplicateCase.ip_record_id_1",
        back_populates="ip_record_1",
        cascade="all, delete-orphan"
    )
    duplicate_cases_2 = relationship(
        "DuplicateCase",
        foreign_keys="DuplicateCase.ip_record_id_2",
        back_populates="ip_record_2",
        cascade="all, delete-orphan"
    )
    conflict_cases = relationship(
        "ConflictCase", back_populates="ip_record", cascade="all, delete-orphan"
    )
    association_requests = relationship(
        "AssociationRequest",
        foreign_keys="AssociationRequest.ip_record_id",
        back_populates="ip_record",
        cascade="all, delete-orphan",
    )


class IpContributor(Base):
    __tablename__ = "ip_contributor"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ip_record_id = Column(String, ForeignKey("ip_record.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("user.id"), nullable=True)

    # Contributor details
    name = Column(String, nullable=False)
    designation = Column(String, nullable=True)
    department = Column(String, nullable=True)
    institution = Column(String, nullable=True)
    contributor_type = Column(String, default="UNKNOWN", nullable=False, index=True)
    author_position = Column(Integer, nullable=True)
    match_confidence = Column(Float, nullable=True)
    match_status = Column(String, default="VERIFICATION_REQUIRED", nullable=False)
    source = Column(String, default="CERTIFICATE_OCR", nullable=False)
    is_external = Column(Boolean, default=False, nullable=False)
    contributor_order = Column(Integer, nullable=False, default=0)

    # Relationships
    ip_record = relationship("IpRecord", back_populates="contributors")
    user = relationship("User", back_populates="ip_contributions")


class ExternalContributor(Base):
    __tablename__ = "external_contributor"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False, unique=True, index=True)
    organization = Column(String, nullable=True)
    country = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: utcnow(), nullable=False)



# --- File Management ---


class IpFile(Base):
    __tablename__ = "ip_file"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ip_record_id = Column(String, ForeignKey("ip_record.id"), nullable=True, index=True)
    master_ip_id = Column(String, ForeignKey("master_ip_record.id"), nullable=True, index=True)
    uploaded_by = Column(String, ForeignKey("user.id"), nullable=True, index=True)

    # File metadata
    storage_key = Column(String, nullable=False, unique=True, index=True)
    original_filename = Column(String, nullable=False)
    file_extension = Column(String, nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    mime_type = Column(String, nullable=True)
    fingerprint = Column(String, nullable=True, index=True)
    document_type = Column(String, default="CERTIFICATE", nullable=False, index=True)

    # Processing metadata
    page_count = Column(Integer, nullable=True)
    width_px = Column(Integer, nullable=True)
    height_px = Column(Integer, nullable=True)

    # Status
    upload_status = Column(String, default="PENDING", nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: utcnow(), nullable=False)

    # Relationships
    ip_record = relationship("IpRecord", back_populates="files")
    master_ip = relationship("MasterIpRecord", back_populates="files")
    uploader = relationship("User", foreign_keys=[uploaded_by])


# --- Processing Jobs ---


class ProcessingJob(Base):
    __tablename__ = "processing_job"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ip_record_id = Column(String, ForeignKey("ip_record.id"), nullable=False, index=True)

    job_type = Column(String, nullable=False, index=True)  # qr, ocr, classify, extract, verify
    status = Column(String, default="PENDING", nullable=False, index=True)

    # Retries & Errors
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    error_message = Column(Text, nullable=True)

    # Results
    result = Column(JSON, nullable=True, default=dict)

    # Timestamps
    created_at = Column(DateTime, default=lambda: utcnow(), nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    ip_record = relationship("IpRecord", back_populates="processing_jobs")


# --- Verification ---


class VerificationAttempt(Base):
    __tablename__ = "verification_attempt"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ip_record_id = Column(String, ForeignKey("ip_record.id"), nullable=False, index=True)

    # Verification details
    source = Column(String, nullable=False)  # e.g., "patent_office", "manual", "api"
    attempt_number = Column(Integer, default=1, nullable=False)
    status = Column(verification_status_enum(), nullable=False)
    result = Column(Text, nullable=True)
    evidence = Column(JSON, nullable=True, default=dict)

    # Timestamps
    created_at = Column(DateTime, default=lambda: utcnow(), nullable=False)

    # Relationships
    ip_record = relationship("IpRecord", back_populates="verification_attempts")


# --- Association Requests ---


class AssociationRequest(Base):
    __tablename__ = "association_request"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ip_record_id = Column(String, ForeignKey("ip_record.id"), nullable=True, index=True)
    master_ip_id = Column(String, ForeignKey("master_ip_record.id"), nullable=True, index=True)
    contributor_id = Column(String, ForeignKey("master_ip_contributor.id"), nullable=True, index=True)
    requesting_faculty_id = Column(String, ForeignKey("user.id"), nullable=False, index=True)
    target_faculty_id = Column(String, ForeignKey("user.id"), nullable=True, index=True)

    # Backwards-compatible aliases used by existing code
    requester_id = Column(String, ForeignKey("user.id"), nullable=True, index=True)
    recipient_id = Column(String, ForeignKey("user.id"), nullable=True, index=True)

    # Request details
    reason = Column(Text, nullable=True)
    message = Column(Text, nullable=True)
    status = Column(association_status_enum(), default="PENDING", nullable=False, index=True)

    # Response
    response_reason = Column(Text, nullable=True)
    clarification_message = Column(Text, nullable=True)
    responder_id = Column(String, ForeignKey("user.id"), nullable=True, index=True)
    responded_at = Column(DateTime, nullable=True)
    reminder_sent_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=lambda: utcnow(), nullable=False)
    responded_at_timestamp = Column(DateTime, nullable=True)

    # Relationships
    master_ip = relationship("MasterIpRecord", foreign_keys=[master_ip_id])
    contributor = relationship("MasterIpContributor", foreign_keys=[contributor_id])
    requester = relationship("User", foreign_keys=[requesting_faculty_id], backref="sent_associations")
    recipient = relationship("User", foreign_keys=[target_faculty_id], backref="received_associations")
    responder = relationship("User", foreign_keys=[responder_id], backref="responded_associations")
    ip_record = relationship("IpRecord", foreign_keys=[ip_record_id], back_populates="association_requests")


# --- Duplicate Cases ---


class DuplicateCase(Base):
    __tablename__ = "duplicate_case"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ip_record_id_1 = Column(String, ForeignKey("ip_record.id"), nullable=False, index=True)
    ip_record_id_2 = Column(String, ForeignKey("ip_record.id"), nullable=False, index=True)

    # Detection details
    detection_method = Column(String, nullable=False)  # fingerprint, identifier, similarity
    confidence = Column(Float, nullable=False)
    detected_by = Column(String, ForeignKey("user.id"), nullable=True, index=True)
    detected_at = Column(DateTime, default=lambda: utcnow(), nullable=False)

    # Resolution
    status = Column(conflict_status_enum(), default="OPEN", nullable=False, index=True)
    kept_record_id = Column(String, nullable=True, index=True)
    resolved_by = Column(String, ForeignKey("user.id"), nullable=True, index=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)

    # Re-upload detection
    fingerprint_match = Column(Boolean, nullable=True, default=False)

    # Relationships
    ip_record_1 = relationship(
        "IpRecord",
        foreign_keys=[ip_record_id_1],
        back_populates="duplicate_cases_1"
    )
    ip_record_2 = relationship(
        "IpRecord",
        foreign_keys=[ip_record_id_2],
        back_populates="duplicate_cases_2"
    )
    detected_by_user = relationship("User", foreign_keys=[detected_by])
    resolved_by_user = relationship("User", foreign_keys=[resolved_by])


# --- Identity Conflicts ---


class IdentityConflict(Base):
    __tablename__ = "identity_conflict"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # The potentially matching records
    user_id_1 = Column(String, ForeignKey("user.id"), nullable=False, index=True)
    user_id_2 = Column(String, ForeignKey("user.id"), nullable=False, index=True)

    # Conflict details
    conflict_type = Column(String, nullable=False)  # same_name, name_variation, etc.
    confidence = Column(Float, nullable=False)
    status = Column(conflict_status_enum(), default="OPEN", nullable=False, index=True)

    # Resolution
    resolved_by = Column(String, ForeignKey("user.id"), nullable=True, index=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=lambda: utcnow(), nullable=False)

    # Relationships
    user_1 = relationship("User", foreign_keys=[user_id_1])
    user_2 = relationship("User", foreign_keys=[user_id_2])
    resolved_by_user = relationship("User", foreign_keys=[resolved_by])


# --- Conflict Cases ---


class ConflictCase(Base):
    __tablename__ = "conflict_case"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ip_record_id = Column(String, ForeignKey("ip_record.id"), nullable=True, index=True)
    master_ip_id = Column(String, ForeignKey("master_ip_record.id"), nullable=True, index=True)

    # Conflict details
    conflict_type = Column(String, nullable=False)  # DATA_MISMATCH, IDENTITY_CONFLICT, etc.
    field_name = Column(String, nullable=True)
    detected_value = Column(Text, nullable=True)
    expected_value = Column(Text, nullable=True)
    source_a = Column(String, nullable=True)
    source_b = Column(String, nullable=True)
    severity = Column(String, default="MEDIUM", nullable=False, index=True)
    description = Column(Text, nullable=False)
    status = Column(conflict_status_enum(), default="OPEN", nullable=False, index=True)

    # Assignment & Resolution
    assigned_to = Column(String, ForeignKey("user.id"), nullable=True, index=True)
    resolution = Column(Text, nullable=True)
    resolved_by = Column(String, ForeignKey("user.id"), nullable=True, index=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=lambda: utcnow(), nullable=False)

    # Relationships
    ip_record = relationship(
        "IpRecord",
        back_populates="conflict_cases"
    )
    master_ip = relationship("MasterIpRecord", foreign_keys=[master_ip_id])
    resolved_by_user = relationship("User", foreign_keys=[resolved_by])
    assigned_to_user = relationship("User", foreign_keys=[assigned_to])


# --- Notifications ---


class Notification(Base):
    __tablename__ = "notification"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("user.id"), nullable=False, index=True)

    # Notification details
    type = Column(String, nullable=False)  # upload, verification, association, conflict, admin
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    related_entity_type = Column(String, nullable=True)
    related_entity_id = Column(String, nullable=True)
    priority = Column(String, default="MEDIUM", nullable=False)
    action_url = Column(String, nullable=True)
    action_label = Column(String, nullable=True)

    # Status
    is_read = Column(Boolean, default=False, nullable=False)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: utcnow(), nullable=False)
    expires_at = Column(DateTime, nullable=True)
    meta = Column("meta", JSON, nullable=True, default=dict)

    # Relationships
    user = relationship("User", backref="notifications")


# --- Audit Log ---


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_id = Column(String, ForeignKey("user.id"), nullable=True, index=True)
    actor_role = Column(String, nullable=True)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=False, index=True)
    entity_id = Column(String, nullable=True, index=True)
    target_type = Column(String, nullable=True)
    target_id = Column(String, nullable=True)

    # Before/After state
    previous_value = Column(JSON, nullable=True, default=dict)
    new_value = Column(JSON, nullable=True, default=dict)
    before_state = Column(JSON, nullable=True, default=dict)
    after_state = Column(JSON, nullable=True, default=dict)

    # Details
    details = Column(JSON, nullable=True, default=dict)
    extra = Column(JSON, nullable=True, default=dict)
    ip_address = Column(String, nullable=True)
    reason = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=lambda: utcnow(), nullable=False)

    # Relationships
    actor = relationship("User", foreign_keys=[actor_id])


# --- Security Events ---


class SecurityEvent(Base):
    __tablename__ = "security_event"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    event_type = Column(String, nullable=False)  # login_failure, lockout, etc.
    source_ip = Column(String, nullable=True)
    user_id = Column(String, ForeignKey("user.id"), nullable=True, index=True)

    # Details
    details = Column(JSON, nullable=True, default=dict)

    # Timestamps
    created_at = Column(DateTime, default=lambda: utcnow(), nullable=False)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])


# --- Master IP Record ---


class MasterIpRecord(Base):
    """One underlying patent/design. Multiple IpRecord submissions (certificate,
    grant, publication, supporting docs) may reference this single master record.
    """

    __tablename__ = "master_ip_record"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ip_type = Column(ip_type_enum(), nullable=False, index=True)

    # Canonical identifiers (NOT globally unique - dedupe layer enforces)
    patent_number = Column(String, nullable=True, index=True)
    application_number = Column(String, nullable=True, index=True)
    publication_number = Column(String, nullable=True, index=True)
    design_number = Column(String, nullable=True, index=True)

    title = Column(Text, nullable=True)
    filing_date = Column(DateTime, nullable=True)
    publication_date = Column(DateTime, nullable=True)
    registration_date = Column(DateTime, nullable=True)
    grant_date = Column(DateTime, nullable=True)

    status = Column(String, default="ACTIVE", nullable=False, index=True)
    official_source = Column(String, nullable=True)
    official_source_url = Column(String, nullable=True)
    official_verification_status = Column(String, nullable=True)
    workflow_state = Column(String, default="UPLOADED", nullable=False, index=True)

    # Final verification decision (auditable)
    verification_decision = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=lambda: utcnow(), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: utcnow(),
        onupdate=lambda: utcnow(),
        nullable=False,
    )

    # Relationships
    ip_records = relationship("IpRecord", back_populates="master_ip")
    contributors = relationship("MasterIpContributor", back_populates="master_ip", cascade="all, delete-orphan")
    faculty_associations = relationship("FacultyIpAssociation", back_populates="master_ip", cascade="all, delete-orphan")
    files = relationship("IpFile", back_populates="master_ip")
    verification_attempts = relationship("MasterVerificationAttempt", back_populates="master_ip", cascade="all, delete-orphan")


class MasterIpContributor(Base):
    """Contributor on the master IP record (deduplicated across submissions)."""

    __tablename__ = "master_ip_contributor"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    master_ip_id = Column(String, ForeignKey("master_ip_record.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    contributor_type = Column(String, default="UNKNOWN", nullable=False, index=True)
    matched_faculty_id = Column(String, ForeignKey("user.id"), nullable=True, index=True)
    author_position = Column(Integer, nullable=True)
    match_confidence = Column(Float, nullable=True)
    match_status = Column(String, default="VERIFICATION_REQUIRED", nullable=False)
    institution = Column(String, nullable=True)
    source = Column(String, default="CERTIFICATE_OCR", nullable=False)
    created_at = Column(DateTime, default=lambda: utcnow(), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: utcnow(),
        onupdate=lambda: utcnow(),
        nullable=False,
    )

    # Relationships
    master_ip = relationship("MasterIpRecord", back_populates="contributors")
    matched_faculty = relationship("User", foreign_keys=[matched_faculty_id])


class FacultyIpAssociation(Base):
    """Many-to-many link: one master IP can belong to multiple faculty, each with
    its own verification status and author position."""

    __tablename__ = "faculty_ip_association"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    master_ip_id = Column(String, ForeignKey("master_ip_record.id"), nullable=False, index=True)
    faculty_id = Column(String, ForeignKey("user.id"), nullable=False, index=True)
    contributor_id = Column(String, ForeignKey("master_ip_contributor.id"), nullable=True, index=True)
    author_position = Column(Integer, nullable=True)
    association_status = Column(String, default="PENDING", nullable=False, index=True)
    verification_status = Column(String, default="UNVERIFIED", nullable=False, index=True)
    association_source = Column(String, default="UPLOADER", nullable=False)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: utcnow(), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: utcnow(),
        onupdate=lambda: utcnow(),
        nullable=False,
    )

    # Relationships
    master_ip = relationship("MasterIpRecord", back_populates="faculty_associations")
    faculty = relationship("User", back_populates="faculty_ip_associations")
    contributor = relationship("MasterIpContributor", foreign_keys=[contributor_id])


class FieldProvenance(Base):
    """Tracks where each extracted/verified field value came from."""

    __tablename__ = "field_provenance"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    ip_record_id = Column(String, ForeignKey("ip_record.id"), nullable=True, index=True)
    master_ip_id = Column(String, ForeignKey("master_ip_record.id"), nullable=True, index=True)
    field_name = Column(String, nullable=False, index=True)
    value = Column(Text, nullable=True)
    source = Column(String, default="UNKNOWN", nullable=False, index=True)
    confidence = Column(Float, nullable=True)
    status = Column(String, default="PENDING", nullable=False, index=True)
    certificate_value = Column(Text, nullable=True)
    official_value = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: utcnow(), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: utcnow(),
        onupdate=lambda: utcnow(),
        nullable=False,
    )

    # Relationships
    ip_record = relationship("IpRecord", back_populates="field_provenance")
    master_ip = relationship("MasterIpRecord", foreign_keys=[master_ip_id])


class FacultyProfileSnapshot(Base):
    """Immutable historical snapshot of faculty profile at time of association."""

    __tablename__ = "faculty_profile_snapshot"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    faculty_id = Column(String, ForeignKey("user.id"), nullable=False, index=True)
    master_ip_id = Column(String, ForeignKey("master_ip_record.id"), nullable=False, index=True)
    full_name = Column(String, nullable=True)
    department_name = Column(String, nullable=True)
    designation_name = Column(String, nullable=True)
    captured_at = Column(DateTime, default=lambda: utcnow(), nullable=False)

    # Relationships
    faculty = relationship("User", foreign_keys=[faculty_id])
    master_ip = relationship("MasterIpRecord", foreign_keys=[master_ip_id])


class MasterVerificationAttempt(Base):
    """Verification attempt against the master IP record."""

    __tablename__ = "master_verification_attempt"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    master_ip_id = Column(String, ForeignKey("master_ip_record.id"), nullable=False, index=True)
    source = Column(String, nullable=False)
    attempted_at = Column(DateTime, default=lambda: utcnow(), nullable=False)
    status = Column(String, nullable=False)
    response = Column(JSON, nullable=True, default=dict)
    extracted_data = Column(JSON, nullable=True, default=dict)
    error = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)

    # Relationships
    master_ip = relationship("MasterIpRecord", back_populates="verification_attempts")


# --- Rate Limit State ---


class RateLimitState(Base):
    __tablename__ = "rate_limit_state"

    id = Column(String, primary_key=True)
    key = Column(String, nullable=False, unique=True, index=True)
    count = Column(Integer, default=0, nullable=False)
    reset_at = Column(DateTime, nullable=False)

    updated_at = Column(
        DateTime,
        default=lambda: utcnow(),
        onupdate=lambda: utcnow(),
        nullable=False,
    )

