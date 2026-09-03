-- Create enums
CREATE TYPE user_role_enum AS ENUM ('super_admin', 'hod_admin', 'faculty');
CREATE TYPE ip_type_enum AS ENUM ('PATENT', 'DESIGN_REGISTRATION', 'UNKNOWN_OTHER');
CREATE TYPE processing_status_enum AS ENUM ('PENDING', 'QUEUED', 'PROCESSING', 'AWAITING_REVIEW', 'COMPLETED', 'FAILED');
CREATE TYPE verification_status_enum AS ENUM ('UNVERIFIED', 'VERIFICATION_REQUIRED', 'VERIFIED', 'MISMATCH');
CREATE TYPE association_status_enum AS ENUM ('PENDING', 'APPROVED', 'REJECTED', 'CLARIFICATION_REQUESTED', 'CANCELLED');
CREATE TYPE conflict_status_enum AS ENUM ('OPEN', 'RESOLVED', 'DISMISSED');

-- user table
CREATE TABLE "user" (
    id VARCHAR PRIMARY KEY,
    email VARCHAR NOT NULL UNIQUE,
    password_hash VARCHAR NOT NULL,
    full_name VARCHAR NOT NULL,
    role user_role_enum NOT NULL DEFAULT 'faculty',
    faculty_id VARCHAR UNIQUE,
    department_id VARCHAR REFERENCES department(id),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- department table
CREATE TABLE department (
    id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL UNIQUE,
    code VARCHAR UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- designation table
CREATE TABLE designation (
    id VARCHAR PRIMARY KEY,
    title VARCHAR NOT NULL UNIQUE,
    level VARCHAR,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- external_contributor table
CREATE TABLE external_contributor (
    id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL UNIQUE,
    organization VARCHAR,
    country VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- rate_limit_state table
CREATE TABLE rate_limit_state (
    id VARCHAR PRIMARY KEY,
    key VARCHAR NOT NULL UNIQUE,
    count INTEGER NOT NULL DEFAULT 0,
    reset_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ip_record table
CREATE TABLE ip_record (
    id VARCHAR PRIMARY KEY,
    ip_type ip_type_enum NOT NULL,
    patent_number VARCHAR UNIQUE,
    application_number VARCHAR UNIQUE,
    design_number VARCHAR UNIQUE,
    serial_number VARCHAR UNIQUE,
    title TEXT,
    patentee VARCHAR,
    applicant VARCHAR,
    published_date TIMESTAMPTZ,
    filing_date TIMESTAMPTZ,
    grant_date TIMESTAMPTZ,
    contributor_name VARCHAR,
    contributor_designation VARCHAR,
    contributor_department VARCHAR,
    contributor_country VARCHAR,
    verification_status verification_status_enum NOT NULL DEFAULT 'UNVERIFIED',
    processing_status processing_status_enum NOT NULL DEFAULT 'PENDING',
    uploader_id VARCHAR NOT NULL REFERENCES "user"(id),
    department_id VARCHAR REFERENCES department(id),
    designation_id VARCHAR REFERENCES designation(id),
    evidence JSON,
    qr_data TEXT,
    certificate_type VARCHAR,
    source_reference VARCHAR,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ip_contributor table
CREATE TABLE ip_contributor (
    id VARCHAR PRIMARY KEY,
    ip_record_id VARCHAR NOT NULL REFERENCES ip_record(id) ON DELETE CASCADE,
    user_id VARCHAR REFERENCES "user"(id),
    name VARCHAR NOT NULL,
    designation VARCHAR,
    department VARCHAR,
    is_external BOOLEAN NOT NULL DEFAULT FALSE,
    contributor_order INTEGER NOT NULL DEFAULT 0
);

-- ip_file table
CREATE TABLE ip_file (
    id VARCHAR PRIMARY KEY,
    ip_record_id VARCHAR REFERENCES ip_record(id) ON DELETE CASCADE,
    storage_key VARCHAR NOT NULL UNIQUE,
    original_filename VARCHAR NOT NULL,
    file_extension VARCHAR NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    mime_type VARCHAR,
    fingerprint VARCHAR,
    page_count INTEGER,
    width_px INTEGER,
    height_px INTEGER,
    upload_status VARCHAR NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- processing_job table
CREATE TABLE processing_job (
    id VARCHAR PRIMARY KEY,
    ip_record_id VARCHAR NOT NULL REFERENCES ip_record(id) ON DELETE CASCADE,
    job_type VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'PENDING',
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    error_message TEXT,
    result JSON,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

-- verification_attempt table
CREATE TABLE verification_attempt (
    id VARCHAR PRIMARY KEY,
    ip_record_id VARCHAR NOT NULL REFERENCES ip_record(id) ON DELETE CASCADE,
    source VARCHAR NOT NULL,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    status verification_status_enum NOT NULL,
    result TEXT,
    evidence JSON,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- association_request table
CREATE TABLE association_request (
    id VARCHAR PRIMARY KEY,
    requester_id VARCHAR NOT NULL REFERENCES "user"(id),
    recipient_id VARCHAR REFERENCES "user"(id),
    reason TEXT,
    status association_status_enum NOT NULL DEFAULT 'PENDING',
    response_reason TEXT,
    responder_id VARCHAR REFERENCES "user"(id),
    responded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    responded_at_timestamp TIMESTAMPTZ
);

-- duplicate_case table
CREATE TABLE duplicate_case (
    id VARCHAR PRIMARY KEY,
    ip_record_id_1 VARCHAR NOT NULL REFERENCES ip_record(id) ON DELETE CASCADE,
    ip_record_id_2 VARCHAR NOT NULL REFERENCES ip_record(id) ON DELETE CASCADE,
    detection_method VARCHAR NOT NULL,
    confidence FLOAT NOT NULL,
    detected_by VARCHAR REFERENCES "user"(id),
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status conflict_status_enum NOT NULL DEFAULT 'OPEN',
    kept_record_id VARCHAR,
    resolved_by VARCHAR REFERENCES "user"(id),
    resolved_at TIMESTAMPTZ,
    resolution_notes TEXT
);

-- identity_conflict table
CREATE TABLE identity_conflict (
    id VARCHAR PRIMARY KEY,
    user_id_1 VARCHAR NOT NULL REFERENCES "user"(id),
    user_id_2 VARCHAR NOT NULL REFERENCES "user"(id),
    conflict_type VARCHAR NOT NULL,
    confidence FLOAT NOT NULL,
    status conflict_status_enum NOT NULL DEFAULT 'OPEN',
    resolved_by VARCHAR REFERENCES "user"(id),
    resolved_at TIMESTAMPTZ,
    resolution_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- conflict_case table
CREATE TABLE conflict_case (
    id VARCHAR PRIMARY KEY,
    ip_record_id VARCHAR NOT NULL REFERENCES ip_record(id) ON DELETE CASCADE,
    conflict_type VARCHAR NOT NULL,
    description TEXT NOT NULL,
    status conflict_status_enum NOT NULL DEFAULT 'OPEN',
    resolved_by VARCHAR REFERENCES "user"(id),
    resolved_at TIMESTAMPTZ,
    resolution_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- notification table
CREATE TABLE notification (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR NOT NULL REFERENCES "user"(id),
    type VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    message TEXT NOT NULL,
    related_entity_type VARCHAR,
    related_entity_id VARCHAR,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- audit_log table
CREATE TABLE audit_log (
    id VARCHAR PRIMARY KEY,
    actor_id VARCHAR REFERENCES "user"(id),
    action VARCHAR NOT NULL,
    target_type VARCHAR NOT NULL,
    target_id VARCHAR,
    before_state JSON,
    after_state JSON,
    details JSON,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- security_event table
CREATE TABLE security_event (
    id VARCHAR PRIMARY KEY,
    event_type VARCHAR NOT NULL,
    source_ip VARCHAR,
    user_id VARCHAR REFERENCES "user"(id),
    details JSON,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- alembic_version table
CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL PRIMARY KEY
);

-- Insert initial alembic version
INSERT INTO alembic_version (version_num) VALUES ('001');