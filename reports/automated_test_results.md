# FPP Automated Test Results Report

**Audit Execution Date:** 2026-10-26  
**Auditor:** QA Automation Engineer & DevOps Specialist  
**Test Frameworks:**
- Frontend: Vitest 5.0.1, React Testing Library, JSDOM, TypeScript 7.0.2
- Backend: Pytest 9.1.1, pytest-asyncio, Starlette TestClient, SQLAlchemy AsyncSession
- Test Database: Disposable PostgreSQL 16 on `localhost:5432` (`test_fpp`) migrated to head (`012`)

---

## 1. Automated Test Execution Summary

| Test Domain | Test Framework | Suites / Files | Total Tests | Passed | Failed | Skipped | Pass Rate | Execution Duration |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Frontend Unit & Component** | Vitest 5.0.1 | 19 | 139 | 139 | 0 | 0 | **100%** | 8.18s |
| **Backend Unit & Integration** | Pytest 9.1.1 | 55 | 555 | 544 | 0 | 11 | **100% (excl. skips)** | 6m 27s |
| **Frontend Production Build** | Vite 8 + TSC | 1 | 1998 modules | 1998 | 0 | 0 | **100%** | 1.80s |
| **Overall Combined Suite** | Full Stack | **75 suites** | **694 tests** | **683** | **0** | **11** | **98.4% (100% clean)** | ~6m 37s |

---

## 2. Frontend Test Suite Breakdown (19 Test Suites, 139 Tests)

| Test File | Tests Passed | Duration | Domain / Feature Under Test |
| :--- | :---: | :---: | :--- |
| `src/features/faculty/AssociationsPage.accept.test.tsx` | 2 | 740ms | Co-inventor association acceptance and inbox state |
| `src/features/hod/HodVerifyGate.test.tsx` | 2 | 733ms | Read-only HOD document view and action isolation |
| `src/features/faculty/UploadPage.cancel.test.tsx` | 2 | 1076ms | Upload abort handling and cancellation cleanup |
| `src/features/notifications/NotificationBell.test.tsx` | 4 | 1133ms | In-app notifications popover, unread counts, mark read |
| `src/features/faculty/UploadPage.uploadsize.test.tsx` | 8 | 1187ms | Client-side file size caps and guidance messages |
| `src/features/admin/AdminGrantedPatentsPage.filter.test.tsx` | 2 | 782ms | Granted patent filters mapping to `workflow_state=GRANTED` |
| `src/testing/legacyGuard.test.ts` | 50 | 42ms | Legacy schema and regression guard assertions |
| `src/features/faculty/associationEligibility.test.ts` | 13 | 24ms | Co-inventor association rules and contributor parsing |
| `src/features/admin/AdminRecordsPage.export.test.tsx` | 5 | 1997ms | Institutional export workflow, format and column selection |
| `src/features/faculty/RecordDetailPage.assoc.test.tsx` | 8 | 2038ms | Association request dispatching and duplicate guards |
| `src/components/ui.names.test.ts` | 5 | 11ms | Faculty and department naming utilities |
| `src/features/admin/AdminFacultyPage.delete.test.tsx` | 5 | 2857ms | Faculty deactivation vs deletion and confirmation modal |
| `src/features/admin/AdminFacultyPage.email.test.tsx` | 3 | 2449ms | Official email input and create button state |
| `src/features/auth/LoginPage.reset.test.tsx` | 12 | 3295ms | Login, forgot password modal, and password reset views |
| `src/api/ui.test.ts` | 6 | 34ms | UI helper and error message formatting |
| `src/features/hod/HodAuditPage.names.test.tsx` | 2 | 145ms | HOD audit log actor name rendering |
| `src/features/faculty/FacultyDashboardPage.summary.test.tsx` | 1 | 109ms | Faculty dashboard metrics rendering |
| `src/api/client.csrf.test.ts` | 6 | 40ms | CSRF header injection and Bearer token synchronization |
| `src/features/faculty/RecordDetailPage.dates.test.tsx` | 3 | 253ms | Controlled draft date input binding and auto-polling |

---

## 3. Backend Test Suite Breakdown (55 Files, 555 Tests)

### Major Test Clusters
1. **Authentication, Tokens & Cookies (12 suites):**
   - `test_auth_cookie.py`, `test_login_enumeration.py`, `test_password_reset.py`, `test_audit_issues_regression.py`, `test_api_workflows.py`.
   - Verified Argon2id password hashing, JWT expiration, token type separation (`access` vs `refresh`), dual cookie rotation, and 401 unauthenticated defenses.
2. **Date Extraction, Normalization & Storage (6 suites):**
   - `test_record_dates_serialization.py`, `test_grant_date_matrix.py`, `test_granted_filter.py`, `test_serial_number_persistence.py`.
   - Verified SQL `Date` column mapping for `grant_date` and `certificate_date`, preventing timezone shifts across ISO serialization.
3. **Department & HOD Governance (8 suites):**
   - `test_admin_governance.py`, `test_hod_manual_verification.py`, `test_hod_audit_names.py`, `test_hod_detail_scoping.py`.
   - Verified department alias resolution ("AIDS" <-> "AIADS"), UUID lookup, and `uq_active_hod_per_department` partial unique constraint.
4. **Co-Inventor Associations & Deduplication (7 suites):**
   - `test_assoc_uniqueness.py`, `test_association_lifecycle.py`, `test_grant_assoc_negatives.py`.
   - Verified partial unique index `uq_assoc_live_pair` and status transition lifecycle.
5. **Security, CSRF & File Storage (10 suites):**
   - `test_grant_csrf.py`, `test_gdrive_storage.py`, `test_storage_service.py`, `test_hardening.py`.
   - Verified file extension whitelisting, magic byte validation, filename sanitization, and Google Drive upload resilience.

### Explanatory Note on 11 Skipped Tests
The 11 tests marked `SKIPPED` represent conditional tests designed for pre-seeded staging environments with mock PDF artifacts attached (`test_hardening.py`, `test_batch5_authz.py`, `test_regression_fixes.py`). When run against an empty disposable local test database, they cleanly evaluate `pytest.skip("no dept-scoped record with file available")` without error.

---

## 4. Production Build Verification

```bash
> faculty-profile-portal-frontend@1.0.0 build
> tsc -b && vite build

vite v8.2.2 building client environment for production...
transforming...
✓ 1998 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                                    1.08 kB │ gzip:  0.59 kB
dist/assets/index-CjaJuUG5.css                    16.91 kB │ gzip:  4.38 kB
dist/assets/RecordDetailPage-h_yneZAL.js          21.35 kB │ gzip:  6.46 kB
dist/assets/LoginPage-7JqQwaMX.js                114.29 kB │ gzip: 34.15 kB
dist/assets/index-Cj4JNwqs.js                    284.94 kB │ gzip: 89.37 kB
✓ built in 1.80s
```

Result: **0 build errors, 0 type errors, 0 bundle warnings**.
