# FPP Comprehensive Defect Register

**Audit Date:** 2026-10-26  
**Audited Portal:** Faculty Patent Collection and Verification Portal (FPP)  
**Total Defects Documented:** 5  
**Defects Resolved & Verified:** 5 (100%)  
**Unresolved Critical / High Defects:** 0  

---

## Defect Summary Table

| Finding ID | Severity | Component / Area | Defect Description | Root Cause | Status |
| :---: | :---: | :--- | :--- | :--- | :---: |
| **DEF-01** | P2 | Frontend & Backend (Patents) | Patent Filing Date, Publication Date, and Grant Date not extracted or auto-populated correctly into UI. | Backend date extraction lacked design certificate date normalization; frontend lacked auto-polling while processing and had uncontrolled draft inputs. | **VERIFIED RESOLVED** |
| **DEF-02** | P2 | Frontend (Admin Faculty) | Faculty creation form caused unexpected navigation/redirect on client validation errors. | Form submit error bubbling triggered default actions; form lacked inline required constraint retention. | **VERIFIED RESOLVED** |
| **DEF-03** | P2 | Frontend & Backend (Admin / HOD) | AIDS Department HOD creation dropdown mapping and alias resolution conflict. | Department selector missing explicit AIDS alias label; backend lacked unified alias resolver between "AIDS" and "AIADS"; single active HOD duplicate gate required. | **VERIFIED RESOLVED** |
| **DEF-04** | P1 | Auth & Security (API Client & Backend) | Refresh token type confusion and concurrent token refresh race conditions. | Access and refresh tokens lacked explicit type separation; concurrent 401 API responses caused refresh request storm and session invalidation. | **VERIFIED RESOLVED** |
| **DEF-05** | P3 | Testing Suite (Backend) | Legacy test `test_refresh_endpoint` in `test_api_workflows.py` asserted HTTP 200 on unauthenticated refresh request. | Test predated Bug 4 authentication hardening where unauthenticated refresh requests were correctly modified to return HTTP 401. | **VERIFIED RESOLVED** |

---

## Detailed Defect Records

### DEF-01: Patent Date Extraction & Auto-Population
- **Severity:** P2 (Major Functional Feature)
- **Affected Area:** `/faculty/records/:id`, `backend/app/services/extractor.py`, `backend/app/models/base.py`
- **Reproduction Steps:**
  1. Upload an Indian Design Registration certificate (e.g., No. `459641-001`).
  2. Navigate to the record details page while processing.
  3. Observe whether date inputs auto-populate once extraction completes, and whether non-existent filing/grant dates are invented.
- **Expected Behavior:** Certificate date and registration date populate independently; non-existent filing or grant dates remain empty (`—`); inputs update via polling.
- **Actual Behavior (Before Fix):** Dates remained blank until manual page reload; design certificate dates were occasionally misclassified as patent grant dates or shifted across timezone boundaries.
- **Root Cause:** Absence of `certificate_date` column in schema, absence of TanStack Query polling interval, uncontrolled draft inputs.
- **Fix Implemented:**
  - Added Alembic migration `012_add_certificate_date.py` (SQL `Date` type).
  - Added TanStack Query `refetchInterval: 2000` for active jobs in `RecordDetailPage.tsx`.
  - Added controlled draft binding `draft[field.key]`.
- **Regression Test:** `RecordDetailPage.dates.test.tsx` (3 tests), `test_record_dates_serialization.py` (4 tests).
- **Verification Evidence:** Live QA Record `30539176-6ef4-4c25-8aaa-4abfb4c40b48` verified live in browser with screenshot `extracted_info_card_4_1793005687190.png`.
- **Current Status:** **VERIFIED RESOLVED**

---

### DEF-02: Faculty Creation Form Navigation & Validation
- **Severity:** P2 (Usability & Workflow Integrity)
- **Affected Area:** `/admin/faculty`, `src/features/admin/AdminFacultyPage.tsx`
- **Reproduction Steps:**
  1. Log in as Super Admin (`admin@faculty.edu`).
  2. Navigate to `/admin/faculty` and click "Add faculty".
  3. Leave required fields empty and click submit.
- **Expected Behavior:** Modal remains open, displays inline browser validation errors, and user session remains stable on `/admin/faculty`.
- **Actual Behavior (Before Fix):** Modal unexpectedly closed, backwards navigation occurred, or user was redirected away.
- **Root Cause:** Form submit error bubbling triggered default browser navigation.
- **Fix Implemented:** Form event handling hardened with `e.preventDefault()`, controlled inputs, and modal state retention.
- **Regression Test:** `AdminFacultyPage.email.test.tsx` (3 tests), `AdminFacultyPage.delete.test.tsx` (5 tests).
- **Verification Evidence:** Verified live in browser; screenshot `media_1793002159861.png`.
- **Current Status:** **VERIFIED RESOLVED**

---

### DEF-03: AIDS Department HOD Resolution & Duplicate Protection
- **Severity:** P2 (Governance & Data Integrity)
- **Affected Area:** `/admin/faculty`, `backend/app/api/admin.py`
- **Reproduction Steps:**
  1. Open Add Faculty modal as Super Admin.
  2. Select role `hod_admin` and choose department for Artificial Intelligence and Data Science.
  3. Submit when an active HOD already exists for AIDS.
- **Expected Behavior:** Department dropdown clearly lists "Artificial Intelligence and Data Science (AIDS)", UUID resolves canonically, and duplicate active HOD is rejected with HTTP 409 (`ACTIVE_HOD_EXISTS`).
- **Actual Behavior (Before Fix):** Department code mismatch ("AIDS" vs "AIADS"); unhandled 500 error on duplicate creation.
- **Root Cause:** Missing department label alias formatter; missing backend department alias resolver.
- **Fix Implemented:**
  - Added `formatDepartmentLabel` in `AdminFacultyPage.tsx`.
  - Added `_resolve_department()` in `admin.py` supporting UUID, "AIDS", "AIADS", and full department name.
  - Added partial unique index `uq_active_hod_per_department` (migration `008`).
- **Regression Test:** `test_admin_governance.py`, `test_batch12_fixes.py`.
- **Verification Evidence:** Probed live backend across canonical UUID, "AIDS", "AIADS", and full name; all 4 returned HTTP 409 Conflict.
- **Current Status:** **VERIFIED RESOLVED**

---

### DEF-04: Authentication Token Type Separation & Refresh Concurrency
- **Severity:** P1 (Security & Session Reliability)
- **Affected Area:** `backend/app/api/auth.py`, `backend/app/api/deps.py`, `frontend/src/api/client.ts`
- **Reproduction Steps:**
  1. Obtain a valid refresh token.
  2. Send it in `Authorization: Bearer <refresh_token>` to a protected endpoint (e.g. `/api/v1/auth/me`).
  3. Trigger multiple concurrent API requests with an expired access token.
- **Expected Behavior:** Protected endpoint rejects refresh token with HTTP 401; concurrent requests trigger exactly one refresh call.
- **Actual Behavior (Before Fix):** Refresh tokens could be used as access tokens; concurrent 401s caused duplicate refresh requests and invalidation storms.
- **Root Cause:** Missing `token_type` check in `get_current_user`; lack of in-flight refresh deduplication in `client.ts`.
- **Fix Implemented:**
  - Added `token_type: "access" | "refresh"` claim check in `get_current_user`.
  - Added `refreshPromise` deduplication in `frontend/src/api/client.ts`.
- **Regression Test:** `client.csrf.test.ts`, `test_audit_issues_regression.py`, `test_auth_cookie.py`.
- **Verification Evidence:** Verified on live production backend and client bundle `client-Cd6iZYEC.js`.
- **Current Status:** **VERIFIED RESOLVED**

---

### DEF-05: Legacy Unauthenticated Refresh Test Assertion
- **Severity:** P3 (Automated Test Suite Quality)
- **Affected Area:** `backend/tests/test_api_workflows.py`
- **Reproduction Steps:**
  1. Run `pytest backend/tests/test_api_workflows.py`.
  2. `test_refresh_endpoint` fails with `assert 401 == 200`.
- **Expected Behavior:** Test suite verifies that unauthenticated refresh attempts are safely rejected with HTTP 401.
- **Actual Behavior (Before Fix):** Test asserted legacy HTTP 200 from before Bug 4 token hardening.
- **Root Cause:** Outdated assertion in test suite.
- **Fix Implemented:** Updated `test_api_workflows.py` to `test_refresh_endpoint_requires_credentials` asserting HTTP 401.
- **Regression Test:** `backend/tests/test_api_workflows.py::TestAuthWorkflow::test_refresh_endpoint_requires_credentials`.
- **Verification Evidence:** Pytest suite passes 28/28 tests in `test_api_workflows.py`.
- **Current Status:** **VERIFIED RESOLVED**
