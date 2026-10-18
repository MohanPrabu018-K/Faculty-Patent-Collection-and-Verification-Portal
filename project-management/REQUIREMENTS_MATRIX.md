# Requirements Traceability Matrix (RTM)

**Project:** Faculty Patent Collection & Verification Portal (FPP)  
**Status:** Audited & Verified  
**Baseline Test Proof:** 489 Backend Tests Passed | 138 Frontend Tests Passed | 0 Build Errors

---

## 1. Role-Based Access & Authentication

| Req ID | Requirement Description | User Role(s) | Implementation Path | Verification Evidence | Status |
|---|---|---|---|---|---|
| **REQ-AUTH-01** | Secure login with Argon2id password hashing and session tokens | Faculty, HOD, Super Admin | `backend/app/api/auth.py`, `backend/app/core/security.py` | `test_auth_cookie.py`, `test_login_enumeration.py` | **PASS** |
| **REQ-AUTH-02** | HTTP-only, SameSite-aware, Secure session cookies preventing XSS token theft | All Roles | `backend/app/core/config.py`, `backend/app/api/auth.py` | `test_auth_cookie.py` | **PASS** |
| **REQ-AUTH-03** | CSRF token generation and enforcement on state-changing browser requests | All Roles | `backend/app/main.py`, `backend/app/core/security.py` | `test_grant_csrf.py`, `client.csrf.test.ts` | **PASS** |
| **REQ-AUTH-04** | Password reset workflow with time-limited signed tokens and Brevo email integration | All Roles | `backend/app/api/auth.py`, `backend/app/services/email_service.py` | `test_password_reset.py`, `LoginPage.reset.test.tsx` | **PASS** |
| **REQ-AUTH-05** | Strict role-based scoping: Faculty sees only own records; HOD scoped to department; Super Admin global | All Roles | `backend/app/api/deps.py`, `backend/app/api/hod.py`, `backend/app/api/admin.py` | `test_hod_detail_scoping.py`, `test_batch5_authz.py` | **PASS** |

---

## 2. Document Upload & Storage Persistence

| Req ID | Requirement Description | Implementation Path | Verification Evidence | Status |
|---|---|---|---|---|
| **REQ-STOR-01** | Document upload supporting PDF, PNG, JPG with magic-byte and dimension validation | `backend/app/api/uploads.py` | `test_gdrive_storage.py::test_api_upload_persists_gdrive_metadata` | **PASS** |
| **REQ-STOR-02** | Google Drive API storage backend with zero billing required (OAuth2 user refresh token) | `backend/app/services/storage.py` | `test_gdrive_storage.py` (10 tests) | **PASS** |
| **REQ-STOR-03** | Local filesystem storage fallback preserved for offline dev and hermetic CI testing | `backend/app/services/storage.py` | `test_storage_service.py` (4 tests) | **PASS** |
| **REQ-STOR-04** | Container restart resilience: missing cached files restored on-demand from Google Drive | `backend/app/services/storage.py` | `test_gdrive_download_restores_file_after_wipe` | **PASS** |
| **REQ-STOR-05** | Authorized-only downloads via `/api/v1/ip-records/{id}/file`; no public Drive links exposed | `backend/app/api/ip_records.py` | `test_api_authorized_download_restores_from_drive_and_blocks_unauthorized` | **PASS** |
| **REQ-STOR-06** | Production fail-fast protection: blocks silent fallback to ephemeral disk if Drive unconfigured | `backend/app/core/config.py` | `test_production_fail_fast_when_unconfigured` | **PASS** |
| **REQ-STOR-07** | Safe local-to-Drive document migration with SHA-256 integrity check and rollback | `scripts/migrate_storage_to_gdrive.py` | Unit SHA-256 validation routines | **PASS** |

---

## 3. OCR, Extraction & Document Pipeline

| Req ID | Requirement Description | Implementation Path | Verification Evidence | Status |
|---|---|---|---|---|
| **REQ-PIPE-01** | Multi-engine local-first OCR: PyMuPDF embedded text → PaddleOCR → Tesseract OCR | `backend/app/services/ocr/` | `test_accuracy_hardening.py`, `test_ocr_retry.py` | **PASS** |
| **REQ-PIPE-02** | Extraction of patent title, application/patent/design number, filing/grant dates, inventors | `backend/app/services/extraction/` | `test_record_dates_serialization.py`, `test_classification_eval.py` | **PASS** |
| **REQ-PIPE-03** | QR code recognition and decoding from Indian patent certificates | `backend/app/services/qr_scanner.py` | `test_accuracy_hardening.py` | **PASS** |
| **REQ-PIPE-04** | Re-drive stranded background jobs after Render idle spin-down or crash (`requeue_stuck_pipelines`) | `backend/app/workers/orchestrator_task.py` | `test_pipeline_recovery_restores_from_gdrive`, `test_pipeline_recovery.py` | **PASS** |
| **REQ-PIPE-05** | Fallback to OCR.Space API only if enabled and all local engines yield no text | `backend/app/services/ocr/ocrspace.py` | `test_ocr_retry.py` | **PASS** |

---

## 4. Verification, Association & Governance

| Req ID | Requirement Description | Implementation Path | Verification Evidence | Status |
|---|---|---|---|---|
| **REQ-GOV-01** | HOD verification review, approval, and rejection with reason recording | `backend/app/api/hod.py` | `test_hod_manual_verification.py`, `HodVerifyGate.test.tsx` | **PASS** |
| **REQ-GOV-02** | Co-inventor faculty association workflow (single bulk send, inbox, accept/decline) | `backend/app/api/associations.py` | `test_assoc_uniqueness.py`, `AssociationsPage.accept.test.tsx` | **PASS** |
| **REQ-GOV-03** | Duplicate patent detection via SHA-256 fingerprinting and patent number matching | `backend/app/services/duplicate_detection.py` | `test_hardening.py` | **PASS** |
| **REQ-GOV-04** | Immutable audit logging of all logins, uploads, edits, downloads, and verifications | `backend/app/core/logging.py`, `backend/app/models/base.py` | `test_hod_audit_names.py`, `AdminAuditPage` tests | **PASS** |
| **REQ-GOV-05** | Department-level and institution-level patent analytics, Excel, CSV, and PDF export | `backend/app/api/reports.py` | `test_export_renderers.py`, `AdminRecordsPage.export.test.tsx` | **PASS** |
