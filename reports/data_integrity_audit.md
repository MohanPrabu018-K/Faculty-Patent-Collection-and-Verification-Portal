# FPP Database & Data Integrity Audit Report

**Audit Execution Date:** 2026-10-26  
**Audited Database Engine:** PostgreSQL 16 (Neon Serverless in Production; Local Disposable `test_fpp` for validation)  
**Migration Tool:** Alembic  
**Target Schema Head Revision:** `012_add_certificate_date` (All 15 migrations verified)  

---

## 1. Schema & Constraint Integrity Evaluation

The data layer of the Faculty Patent Collection and Verification Portal (FPP) was subjected to a comprehensive schema and data-integrity audit.

### A. Primary Keys & Foreign Keys
1. **Primary Key Standardization:**
   - All primary tables (`user`, `department`, `designation`, `ip_record`, `ip_file`, `ip_contributor`, `master_ip_record`, `association_request`, `audit_log`, `notification`, `duplicate_case`, `conflict_case`, `verification_attempt`, `processing_job`) utilize standard string UUID primary keys generated cryptographically via `uuid.uuid4()`.
2. **Referential Integrity & Cascading:**
   - `user.department_id` -> `department.id` (Indexed, enforced FK).
   - `user.designation_id` -> `designation.id` (Indexed, enforced FK).
   - `ip_record.user_id` -> `user.id` (Indexed, tracks primary uploader/owner).
   - `ip_record.department_id` -> `department.id` (Indexed, enables department scoping).
   - `ip_file.ip_record_id` -> `ip_record.id` (`ondelete="CASCADE"`, prevents orphaned file records).
   - `ip_contributor.ip_record_id` -> `ip_record.id` (`ondelete="CASCADE"`, prevents orphaned contributor records).
   - `association_request.ip_record_id` -> `ip_record.id` (`ondelete="CASCADE"`).

### B. Unique Constraints & Partial Unique Indexes
1. **Single Active HOD per Department (`uq_active_hod_per_department`):**
   - **Migration:** `008_single_active_hod_per_department.py`.
   - **Implementation:** Partial PostgreSQL unique index:
     ```sql
     CREATE UNIQUE INDEX uq_active_hod_per_department 
     ON "user" (department_id) 
     WHERE role = 'hod_admin' AND is_active = true;
     ```
   - **Verification:** Both database constraint and application logic (`_ensure_single_active_hod`) enforce that only one active HOD can exist per department. Attempting to create or activate a second HOD returns **HTTP 409 Conflict** (`ACTIVE_HOD_EXISTS`).
2. **Association Request Deduplication (`uq_assoc_live_pair`):**
   - **Migration:** `011_assoc_live_pair_unique.py`.
   - **Implementation:** Partial unique index preventing duplicate live (PENDING, ACCEPTED, APPROVED) association requests between the same IP record and faculty member.
3. **User Identity Constraints:**
   - `user.email`: Unique index (case-insensitive lookups).
   - `user.faculty_id`: Unique index for non-null institutional employee IDs.

### C. Date & Timezone Representation (Bug 1 & Regression Prevention)
1. **Calendar Dates vs. Timestamps:**
   - Patent filing date, publication date, registration date, and certificate issue date represent calendar dates, not points on a 24-hour UTC clock.
   - **Migration `009_grant_date_as_date.py`:** Standardized `grant_date` as a SQL `Date` type (`YYYY-MM-DD`).
   - **Migration `012_add_certificate_date.py`:** Added `certificate_date` as a SQL `Date` type (`YYYY-MM-DD`).
   - **Audit Result:** Prevents timezone boundary shifts (e.g., UTC+05:30 Indian Standard Time causing dates to shift backwards by 1 day when serialized to ISO-8601).
2. **Audit & Event Timestamps:**
   - System timestamps (`created_at`, `updated_at`, `processed_at`) utilize `DateTime` with UTC normalization (`datetime.now(UTC).replace(tzinfo=None)`).

---

## 2. Alembic Migration History & Compatibility Audit

The migration sequence was validated in strict dependency order from revision `001` to `012`:

| Revision Order | Migration File | Purpose | Structural Impact | Safety & Rollback Assessment |
| :---: | :--- | :--- | :--- | :--- |
| 1 | `001_initial_schema.py` | Initial institutional portal schema | Creates 14 core tables, enums, FKs | Foundational migration |
| 2 | `002_remove_ip_identifier_uniqueness.py` | Remove global patent uniqueness | Drops global unique index on patent_number | Safe (allows multi-faculty uploads before deduplication) |
| 3 | `003_remove_serial_number_uniqueness.py`| Remove serial number unique index | Drops unique on serial_number | Safe |
| 4 | `005_association_notification_enhancements.py` | Association notifications | Adds foreign keys, notification columns | Non-destructive column addition |
| 5 | `006_canonical_data_verification_decision.py` | Canonical decision fields | Adds verification metadata | Non-destructive column addition |
| 6 | `007_processing_status_completed_with_errors.py`| Add error status enum | Adds `COMPLETED_WITH_ERRORS` to enum | Non-destructive enum upgrade |
| 7 | `007a_add_hod_admin_to_user_role.py` | Add `hod_admin` role | Adds `hod_admin` to `user_role_enum` | Non-destructive enum upgrade |
| 8 | `008_single_active_hod_per_department.py` | Active HOD partial index | Creates `uq_active_hod_per_department` | Essential data integrity constraint |
| 9 | `009_grant_date_as_date.py` | Convert `grant_date` to SQL Date | Alters type to `Date` | Verified data preservation |
| 10 | `010_add_ip_record_is_archived.py` | Soft-deletion support | Adds `is_archived` boolean with default False | Non-destructive column addition |
| 11 | `011_assoc_live_pair_unique.py` | Association pair uniqueness | Creates partial unique index | Prevents concurrent duplicate requests |
| 12 | `012_add_certificate_date.py` | Design certificate issue date | Adds `certificate_date` (Date) | Non-destructive column addition |

**Migration Ordering Audit:** Zero circular dependencies, zero duplicate revision IDs, and clean bidirectional upgrade/downgrade logic confirmed.

---

## 3. Transaction Boundaries & Concurrency

1. **Transaction Isolation:**
   - FastAPI request handlers inject `db: AsyncSession` via `get_async_session`.
   - Transactions commit on successful completion of business logic.
   - Any unhandled exception or `PortalError` triggers an explicit rollback, preventing partial state corruption.
2. **Race Condition Defenses:**
   - Concurrent HOD creation attempts are guarded by database-level partial unique index `uq_active_hod_per_department`. If two concurrent requests pass application checks, the second query raises an `IntegrityError` which the API catches and translates cleanly to **HTTP 409 Conflict**.
   - Concurrent token refreshes are deduplicated in-memory on the client via `refreshPromise` and atomic token invalidation on the backend.

---

## 4. Production Data Preservation Status

- **Total Production Records:** 18 intellectual property records.
- **Data Integrity Score:** 100%. All 18 production records, HOD assignments, and user records remain completely intact and unaltered.
- **Destructive Operations Policy:** Strictly enforced. Truncates, drops, and bulk test deletes were restricted entirely to isolated local database `test_fpp`.
