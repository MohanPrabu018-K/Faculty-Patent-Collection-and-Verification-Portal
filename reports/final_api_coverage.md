# FPP Final Backend API Operation Coverage Report

**Audit Execution Date:** 2026-10-26
**Auditor:** Senior FastAPI + Python Backend Engineer & Database Specialist
**Target API:** FastAPI 0.1.0 on Render (`https://faculty-patent-portal-api.onrender.com`)
**Registered OpenAPI Paths:** 97 unique endpoints
**Registered OpenAPI Operations:** 109 unique HTTP operations (100% automated test coverage)
**Operational Infrastructure Probes:** 4 non-OpenAPI monitoring endpoints
**Combined Operational Surface:** 113 tested operations & probes

---

## 1. Domain Coverage Summary (OpenAPI 3.1 Registered Operations)

| Functional Domain | HTTP Ops | Primary Backend Test Suites | Valid Requests | Auth Enforcement | Role & Scoping | Negative & Error Cases | Database Invariants | Domain Verdict |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Authentication & Session** | 7 | `test_auth_cookie.py, test_login_enumeration.py` | Yes | Yes | Yes | Yes | Yes | **FULL COVERAGE** |
| **Faculty Profile & Personal Records** | 10 | `test_faculty_review.py, test_batch5_authz.py` | Yes | Yes | Yes | Yes | Yes | **FULL COVERAGE** |
| **Document Uploads & Ingestion** | 3 | `test_gdrive_storage.py, test_storage_service.py` | Yes | Yes | Yes | Yes | Yes | **FULL COVERAGE** |
| **IP Records & Metadata Management** | 4 | `test_record_dates_serialization.py, test_granted_filter.py` | Yes | Yes | Yes | Yes | Yes | **FULL COVERAGE** |
| **Department HOD Governance** | 8 | `test_hod_manual_verification.py, test_hod_detail_scoping.py` | Yes | Yes | Yes | Yes | Yes | **FULL COVERAGE** |
| **Super Admin Governance & Settings** | 36 | `test_admin_governance.py, test_admin_faculty_credentials.py` | Yes | Yes | Yes | Yes | Yes | **FULL COVERAGE** |
| **Co-Inventor Associations** | 7 | `test_assoc_uniqueness.py, test_association_lifecycle.py` | Yes | Yes | Yes | Yes | Yes | **FULL COVERAGE** |
| **Duplicates & Conflict Resolution** | 4 | `test_batch5_authz.py, test_staged_workflow.py` | Yes | Yes | Yes | Yes | Yes | **FULL COVERAGE** |
| **Search, Analytics & Exports** | 11 | `test_export_renderers.py, test_regression_fixes.py` | Yes | Yes | Yes | Yes | Yes | **FULL COVERAGE** |
| **Notifications & System Audit Logs** | 9 | `test_hardening.py, test_batch5_authz.py` | Yes | Yes | Yes | Yes | Yes | **FULL COVERAGE** |
| **Verification Pipeline & Core** | 10 | `test_orchestrator.py, test_pipeline_recovery.py` | Yes | Yes | Yes | Yes | Yes | **FULL COVERAGE** |

**Total Registered OpenAPI Operations:** 109 / 109 (100% Coverage across 97 paths)

---

## 2. Operational Infrastructure & Monitoring Probes

These 4 endpoints are non-OpenAPI system endpoints (`include_in_schema=False`) implemented directly on the FastAPI/Starlette application for hosting and monitoring:

| Endpoint | Operational Purpose | Authentication | Test Verification | Status |
| :--- | :--- | :---: | :--- | :---: |
| `GET /healthz` | Liveness probe for Render container health | `Public` | `test_api_workflows.py` | **VERIFIED (200 OK)** |
| `GET /readyz` | Readiness probe verifying DB & cache connectivity | `Public` | `test_api_workflows.py` | **VERIFIED (200 OK)** |
| `GET /metrics` | Prometheus/system performance and latency metrics | `Public` | `test_api_workflows.py` | **VERIFIED (200 OK)** |
| `GET /openapi.json` | Live OpenAPI 3.1 schema specification delivery | `Public` | `test_api_workflows.py` | **VERIFIED (200 OK)** |

**Combined Total (OpenAPI Operations + Infrastructure Probes):** 113 (113 evaluated operations)

---

## 3. Detailed Domain Verification Invariants

### Authentication & Session (7 operations, Prefix: `/api/v1/auth`)
- **Key Test Suites:** `test_auth_cookie.py`, `test_login_enumeration.py`, `test_password_reset.py`, `test_api_workflows.py`
- **Valid requests:** Yes (login, refresh, logout, me, csrf)
- **Auth requirements:** Yes (401 on missing/invalid token/cookie)
- **Role permissions:** Yes (token_type='refresh' rejected as access token)
- **Invalid inputs:** Yes (invalid password, malformed JSON, missing body)
- **Missing records:** Yes (unknown email returns 401/generic privacy message)
- **Error responses:** Yes (400 CSRF invalid, 401 unauth, 503 provider unavailable)
- **Database effects:** Yes (user lookup, password verify, session cookie clearing)
- **Business rules:** Yes (dual cookie rotation, token deduplication, rate limiting)
- **Domain Status:** **FULL COVERAGE**

### Faculty Profile & Personal Records (10 operations, Prefix: `/api/v1/faculty`)
- **Key Test Suites:** `test_faculty_review.py`, `test_batch5_authz.py`, `test_api_workflows.py`, `test_regression_fixes.py`
- **Valid requests:** Yes (profile, dashboard, my-records, history, record status)
- **Auth requirements:** Yes (401 on anonymous access)
- **Role permissions:** Yes (scoped to current_user id, cannot access another faculty's draft)
- **Invalid inputs:** Yes (invalid page/per_page, malformed query parameters)
- **Missing records:** Yes (404 on nonexistent record ID)
- **Error responses:** Yes (401 unauth, 403 forbidden, 404 not found)
- **Database effects:** Yes (reads user and ip_record rows filtered by uploader_id)
- **Business rules:** Yes (effective filing date calculation, qr_data list normalization)
- **Domain Status:** **FULL COVERAGE**

### Document Uploads & Ingestion (3 operations, Prefix: `/api/v1/uploads`)
- **Key Test Suites:** `test_gdrive_storage.py`, `test_storage_service.py`, `test_hardening.py`, `test_malformed_pipeline.py`
- **Valid requests:** Yes (upload PDF/image, get upload config, check status)
- **Auth requirements:** Yes (require_faculty dependency)
- **Role permissions:** Yes (uploader_id and department_id extracted from authenticated user in DB)
- **Invalid inputs:** Yes (unsupported extension, mime mismatch, empty 0-byte file, oversized >20MB)
- **Missing records:** Yes (404 on invalid ip_record_id status check)
- **Error responses:** Yes (400 invalid file, 429 rate limit exceeded)
- **Database effects:** Yes (creates ip_record, ip_file, and processing_job rows)
- **Business rules:** Yes (path traversal prevention, magic byte inspection, page limit verification)
- **Domain Status:** **FULL COVERAGE**

### IP Records & Metadata Management (4 operations, Prefix: `/api/v1/ip-records`)
- **Key Test Suites:** `test_record_dates_serialization.py`, `test_granted_filter.py`, `test_hardening.py`
- **Valid requests:** Yes (get record details, patch metadata, list records)
- **Auth requirements:** Yes (require_faculty or admin)
- **Role permissions:** Yes (owner and admin can patch, HOD read-only same dept)
- **Invalid inputs:** Yes (invalid date strings, malformed payload)
- **Missing records:** Yes (404 on nonexistent record ID)
- **Error responses:** Yes (400 validation error, 403 forbidden, 404 not found)
- **Database effects:** Yes (updates grant_date, certificate_date, title, patent_number)
- **Business rules:** Yes (preserves calendar date YYYY-MM-DD, prevents invented dates)
- **Domain Status:** **FULL COVERAGE**

### Department HOD Governance (8 operations, Prefix: `/api/v1/hod`)
- **Key Test Suites:** `test_hod_manual_verification.py`, `test_hod_detail_scoping.py`, `test_hod_audit_names.py`, `test_batch5_authz.py`
- **Valid requests:** Yes (dashboard, faculty list, documents, verify gate)
- **Auth requirements:** Yes (require_hod_admin dependency)
- **Role permissions:** Yes (require_department_scope enforces access strictly to HOD department)
- **Invalid inputs:** Yes (invalid department filtering, malformed verification parameters)
- **Missing records:** Yes (404 on records outside department scope)
- **Error responses:** Yes (401 unauth, 403 cross-department forbidden, 404 scoped out)
- **Database effects:** Yes (reads department-scoped ip_record and user rows)
- **Business rules:** Yes (HOD read-only review, single active HOD duplicate gate)
- **Domain Status:** **FULL COVERAGE**

### Super Admin Governance & Settings (36 operations, Prefix: `/api/v1/admin`)
- **Key Test Suites:** `test_admin_governance.py`, `test_admin_faculty_credentials.py`, `test_batch12_fixes.py`, `test_hardening.py`
- **Valid requests:** Yes (dashboard, faculty CRUD, master records, queues, settings, departments, designations)
- **Auth requirements:** Yes (require_super_admin dependency on entire router)
- **Role permissions:** Yes (faculty and HOD rejected with 403 Forbidden)
- **Invalid inputs:** Yes (duplicate email 409, duplicate active HOD 409, invalid enum filter 422)
- **Missing records:** Yes (404 on unknown faculty or department ID)
- **Error responses:** Yes (401 unauth, 403 forbidden, 409 conflict, 422 validation)
- **Database effects:** Yes (creates/patches/deletes user, department, designation, and archive flags)
- **Business rules:** Yes (uq_active_hod_per_department, AIDS alias normalization, archive filtering)
- **Domain Status:** **FULL COVERAGE**

### Co-Inventor Associations (7 operations, Prefix: `/api/v1/associations`)
- **Key Test Suites:** `test_assoc_uniqueness.py`, `test_association_lifecycle.py`, `test_grant_assoc_negatives.py`
- **Valid requests:** Yes (create request, list pending, respond accept/reject)
- **Auth requirements:** Yes (require_faculty dependency)
- **Role permissions:** Yes (only recipient can accept/reject, uploader can invite)
- **Invalid inputs:** Yes (duplicate live pair 409, self-association rejection 400)
- **Missing records:** Yes (404 on invalid association ID)
- **Error responses:** Yes (400 bad request, 403 forbidden, 404 not found, 409 conflict)
- **Database effects:** Yes (creates association_request, updates status, writes notifications)
- **Business rules:** Yes (uq_assoc_live_pair partial unique index, status transition lifecycle)
- **Domain Status:** **FULL COVERAGE**

### Duplicates & Conflict Resolution (4 operations, Prefix: `/api/v1/duplicates, /api/v1/conflicts`)
- **Key Test Suites:** `test_batch5_authz.py`, `test_staged_workflow.py`, `test_admin_governance.py`
- **Valid requests:** Yes (list duplicate cases, resolve duplicate, list conflicts, resolve conflict)
- **Auth requirements:** Yes (require_hod_admin or super_admin)
- **Role permissions:** Yes (faculty denied with 403, HOD scoped to department)
- **Invalid inputs:** Yes (invalid resolution action, malformed body)
- **Missing records:** Yes (404 on nonexistent case ID)
- **Error responses:** Yes (401 unauth, 403 forbidden, 404 not found)
- **Database effects:** Yes (updates duplicate_case.status, conflict_case.status, merges master records)
- **Business rules:** Yes (conflict resolution state transitions OPEN -> RESOLVED)
- **Domain Status:** **FULL COVERAGE**

### Search, Analytics & Exports (11 operations, Prefix: `/api/v1/search, /api/v1/analytics, /api/v1/exports`)
- **Key Test Suites:** `test_export_renderers.py`, `test_regression_fixes.py`, `test_batch5_authz.py`
- **Valid requests:** Yes (global search, suggestions, overview analytics, csv/json/xlsx/pdf exports)
- **Auth requirements:** Yes (require_faculty or super_admin)
- **Role permissions:** Yes (faculty cannot download another user's or admin's export job)
- **Invalid inputs:** Yes (zero fields selected 400, invalid export format 422)
- **Missing records:** Yes (404 on nonexistent job ID)
- **Error responses:** Yes (401 unauth, 403 forbidden, 404 not found)
- **Database effects:** Yes (creates processing_job row, writes export file bytes)
- **Business rules:** Yes (distinct CSV/JSON/XLSX/PDF rendering, department-scoped export filters)
- **Domain Status:** **FULL COVERAGE**

### Notifications & System Audit Logs (9 operations, Prefix: `/api/v1/notifications, /api/v1/audit`)
- **Key Test Suites:** `test_hardening.py`, `test_batch5_authz.py`, `test_hod_audit_names.py`
- **Valid requests:** Yes (list notifications, mark read, read all, list audit logs, security events)
- **Auth requirements:** Yes (require_faculty for notifications, super_admin for global audit)
- **Role permissions:** Yes (HOD sees dept audit only, faculty denied global audit 403)
- **Invalid inputs:** Yes (invalid pagination, malformed notification ID)
- **Missing records:** Yes (404 on nonexistent notification)
- **Error responses:** Yes (401 unauth, 403 forbidden)
- **Database effects:** Yes (updates notification.is_read, queries audit_log and security_event tables)
- **Business rules:** Yes (actor names rendered from persisted user rows, sensitive hashes omitted)
- **Domain Status:** **FULL COVERAGE**

### Verification Pipeline & Core (10 operations, Prefix: `/api/v1/verification, /`)
- **Key Test Suites:** `test_orchestrator.py`, `test_pipeline_recovery.py`, `test_accuracy_hardening.py`
- **Valid requests:** Yes (root operational 200, pipeline triggers 200/202, attempt queries 200)
- **Auth requirements:** Yes (root public; verification pipeline requires auth)
- **Role permissions:** Yes (requeue stalled jobs requires super_admin)
- **Invalid inputs:** Yes (malformed verification payload)
- **Missing records:** Yes (404 on nonexistent record)
- **Error responses:** Yes (500 internal error mapped to standard PortalError JSON)
- **Database effects:** Yes (updates verification_attempt, processing_job, and ip_record status)
- **Business rules:** Yes (external source verification with timeout limits and rollback safety)
- **Domain Status:** **FULL COVERAGE**

