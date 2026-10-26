# FPP Complete Route and API Endpoint Inventory
**Audit Execution Date:** 2026-10-26
This inventory documents the complete surface of the Faculty Patent Collection and Verification Portal (FPP), compiled from source code analysis of React Router configuration (`frontend/src/app/App.tsx`) and the live OpenAPI specification (`/openapi.json`) served by the production backend.
---

## 1. Frontend Route Inventory (33 Routes Discovered)

| Path | Page Component | Auth Requirement | Allowed Roles | Direct Nav | Refresh | Guard Block | Test Status |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| `/login` | `LoginPage` | Public | Anonymous / All | Yes | Yes | N/A (Public) | **PASS** |
| `/reset` | `LoginPage (Reset Mode)` | Public | Anonymous / All | Yes | Yes | N/A (Public) | **PASS** |
| `/` | `Navigate to /faculty/dashboard` | Required | All authenticated | Yes (Redirects) | Yes | Yes (Redirects to /login) | **PASS** |
| `/faculty/dashboard` | `FacultyDashboardPage` | Required | faculty, hod_admin, super_admin | Yes | Yes | Yes (Redirects to /login) | **PASS** |
| `/faculty/profile` | `FacultyProfilePage` | Required | faculty, hod_admin, super_admin | Yes | Yes | Yes (Redirects to /login) | **PASS** |
| `/faculty/upload` | `UploadPage` | Required | faculty, hod_admin, super_admin | Yes | Yes | Yes (Redirects to /login) | **PASS** |
| `/faculty/records` | `RecordsPage` | Required | faculty, hod_admin, super_admin | Yes | Yes | Yes (Redirects to /login) | **PASS** |
| `/faculty/records/:recordId` | `RecordDetailPage` | Required | faculty, hod_admin, super_admin | Yes | Yes | Yes (Redirects to /login) | **PASS** |
| `/faculty/associations` | `AssociationsPage` | Required | faculty, hod_admin, super_admin | Yes | Yes | Yes (Redirects to /login) | **PASS** |
| `/faculty/history` | `FacultyHistoryPage` | Required | faculty, hod_admin, super_admin | Yes | Yes | Yes (Redirects to /login) | **PASS** |
| `/notifications` | `NotificationsPage` | Required | faculty, hod_admin, super_admin | Yes | Yes | Yes (Redirects to /login) | **PASS** |
| `/search` | `SearchPage` | Required | faculty, hod_admin, super_admin | Yes | Yes | Yes (Redirects to /login) | **PASS** |
| `/hod/dashboard` | `HodDashboardPage` | Required | hod_admin, super_admin | Yes | Yes | Yes (Faculty blocked with 403 / redirect) | **PASS** |
| `/hod/faculty` | `HodFacultyPage` | Required | hod_admin, super_admin | Yes | Yes | Yes (Faculty blocked with 403 / redirect) | **PASS** |
| `/hod/documents` | `HodDocumentsPage` | Required | hod_admin, super_admin | Yes | Yes | Yes (Faculty blocked with 403 / redirect) | **PASS** |
| `/hod/upload` | `UploadPage (HOD Scoped)` | Required | hod_admin, super_admin | Yes | Yes | Yes (Faculty blocked with 403 / redirect) | **PASS** |
| `/hod/duplicates` | `HodDuplicatesPage` | Required | hod_admin, super_admin | Yes | Yes | Yes (Faculty blocked with 403 / redirect) | **PASS** |
| `/hod/conflicts` | `HodConflictsPage` | Required | hod_admin, super_admin | Yes | Yes | Yes (Faculty blocked with 403 / redirect) | **PASS** |
| `/hod/reports` | `HodReportsPage` | Required | hod_admin, super_admin | Yes | Yes | Yes (Faculty blocked with 403 / redirect) | **PASS** |
| `/hod/audit` | `HodAuditPage` | Required | hod_admin, super_admin | Yes | Yes | Yes (Faculty blocked with 403 / redirect) | **PASS** |
| `/hod/associations` | `AssociationsPage (HOD Scoped)` | Required | hod_admin, super_admin | Yes | Yes | Yes (Faculty blocked with 403 / redirect) | **PASS** |
| `/hod/profile` | `FacultyProfilePage (HOD Profile)` | Required | hod_admin, super_admin | Yes | Yes | Yes (Faculty blocked with 403 / redirect) | **PASS** |
| `/admin/dashboard` | `AdminDashboardPage` | Required | super_admin | Yes | Yes | Yes (HOD & Faculty blocked with 403 / redirect) | **PASS** |
| `/admin/faculty` | `AdminFacultyPage` | Required | super_admin | Yes | Yes | Yes (HOD & Faculty blocked with 403 / redirect) | **PASS** |
| `/admin/granted-patents` | `AdminGrantedPatentsPage` | Required | super_admin | Yes | Yes | Yes (HOD & Faculty blocked with 403 / redirect) | **PASS** |
| `/admin/patent-upload` | `UploadPage (Super Admin)` | Required | super_admin | Yes | Yes | Yes (HOD & Faculty blocked with 403 / redirect) | **PASS** |
| `/admin/ip-records` | `AdminRecordsPage` | Required | super_admin | Yes | Yes | Yes (HOD & Faculty blocked with 403 / redirect) | **PASS** |
| `/admin/master-records` | `AdminMasterRecordsPage` | Required | super_admin | Yes | Yes | Yes (HOD & Faculty blocked with 403 / redirect) | **PASS** |
| `/admin/queues` | `AdminQueuesPage` | Required | super_admin | Yes | Yes | Yes (HOD & Faculty blocked with 403 / redirect) | **PASS** |
| `/admin/reports` | `AdminReportsPage` | Required | super_admin | Yes | Yes | Yes (HOD & Faculty blocked with 403 / redirect) | **PASS** |
| `/admin/excel-import` | `AdminExcelImportPage` | Required | super_admin | Yes | Yes | Yes (HOD & Faculty blocked with 403 / redirect) | **PASS** |
| `/admin/audit` | `AdminAuditPage` | Required | super_admin | Yes | Yes | Yes (HOD & Faculty blocked with 403 / redirect) | **PASS** |
| `/admin/settings` | `AdminSettingsPage` | Required | super_admin | Yes | Yes | Yes (HOD & Faculty blocked with 403 / redirect) | **PASS** |

### Frontend Route Details & API Dependencies

#### `/login` (LoginPage)
- **Description:** User authentication, login via email/password, forgot password trigger.
- **Allowed Roles:** `Anonymous / All`
- **API Dependencies:** `POST /api/v1/auth/login`, `POST /api/v1/auth/forgot-password`
- **Unauthenticated Access Guard:** N/A (Public)

#### `/reset` (LoginPage (Reset Mode))
- **Description:** Password reset execution via emailed token parameter (?token=...).
- **Allowed Roles:** `Anonymous / All`
- **API Dependencies:** `POST /api/v1/auth/reset-password`
- **Unauthenticated Access Guard:** N/A (Public)

#### `/` (Navigate to /faculty/dashboard)
- **Description:** Root index redirect to faculty dashboard.
- **Allowed Roles:** `All authenticated`
- **API Dependencies:** None
- **Unauthenticated Access Guard:** Yes (Redirects to /login)

#### `/faculty/dashboard` (FacultyDashboardPage)
- **Description:** Personal IP metrics, submission stats, status distribution, recent uploads.
- **Allowed Roles:** `faculty, hod_admin, super_admin`
- **API Dependencies:** `GET /api/v1/faculty/dashboard`
- **Unauthenticated Access Guard:** Yes (Redirects to /login)

#### `/faculty/profile` (FacultyProfilePage)
- **Description:** Faculty profile information, department, designation, publication metrics.
- **Allowed Roles:** `faculty, hod_admin, super_admin`
- **API Dependencies:** `GET /api/v1/faculty/profile`
- **Unauthenticated Access Guard:** Yes (Redirects to /login)

#### `/faculty/upload` (UploadPage)
- **Description:** Upload patent or design registration PDF, client validation, progress tracking.
- **Allowed Roles:** `faculty, hod_admin, super_admin`
- **API Dependencies:** `POST /api/v1/uploads/`, `GET /api/v1/uploads/config`
- **Unauthenticated Access Guard:** Yes (Redirects to /login)

#### `/faculty/records` (RecordsPage)
- **Description:** Browse personal patent records, filter by type/status, pagination, search.
- **Allowed Roles:** `faculty, hod_admin, super_admin`
- **API Dependencies:** `GET /api/v1/faculty/my-records`
- **Unauthenticated Access Guard:** Yes (Redirects to /login)

#### `/faculty/records/:recordId` (RecordDetailPage)
- **Description:** Record details, extraction results, auto-polling (2s), metadata editing, associations.
- **Allowed Roles:** `faculty, hod_admin, super_admin`
- **API Dependencies:** `GET /api/v1/ip-records/{record_id}`, `PATCH /api/v1/ip-records/{record_id}`, `POST /api/v1/associations/`
- **Unauthenticated Access Guard:** Yes (Redirects to /login)

#### `/faculty/associations` (AssociationsPage)
- **Description:** Manage co-inventor associations, accept/reject pending association invites.
- **Allowed Roles:** `faculty, hod_admin, super_admin`
- **API Dependencies:** `GET /api/v1/associations/`, `POST /api/v1/associations/{id}/respond`
- **Unauthenticated Access Guard:** Yes (Redirects to /login)

#### `/faculty/history` (FacultyHistoryPage)
- **Description:** Historical timeline of submissions, status transitions, and audit records.
- **Allowed Roles:** `faculty, hod_admin, super_admin`
- **API Dependencies:** `GET /api/v1/faculty/history`
- **Unauthenticated Access Guard:** Yes (Redirects to /login)

#### `/notifications` (NotificationsPage)
- **Description:** In-app notifications feed, mark as read, unread counts, status updates.
- **Allowed Roles:** `faculty, hod_admin, super_admin`
- **API Dependencies:** `GET /api/v1/notifications/`, `POST /api/v1/notifications/read-all`
- **Unauthenticated Access Guard:** Yes (Redirects to /login)

#### `/search` (SearchPage)
- **Description:** Global institutional IP search, keyword suggestions, filter by year/dept/type.
- **Allowed Roles:** `faculty, hod_admin, super_admin`
- **API Dependencies:** `GET /api/v1/search/`, `GET /api/v1/search/suggestions`
- **Unauthenticated Access Guard:** Yes (Redirects to /login)

#### `/hod/dashboard` (HodDashboardPage)
- **Description:** Departmental IP overview, pending reviews count, departmental patent statistics.
- **Allowed Roles:** `hod_admin, super_admin`
- **API Dependencies:** `GET /api/v1/hod/dashboard`
- **Unauthenticated Access Guard:** Yes (Faculty blocked with 403 / redirect)

#### `/hod/faculty` (HodFacultyPage)
- **Description:** List faculty members within the HOD's department, IP metrics per member.
- **Allowed Roles:** `hod_admin, super_admin`
- **API Dependencies:** `GET /api/v1/hod/faculty`
- **Unauthenticated Access Guard:** Yes (Faculty blocked with 403 / redirect)

#### `/hod/documents` (HodDocumentsPage)
- **Description:** Department document repository, review submissions, trigger verification.
- **Allowed Roles:** `hod_admin, super_admin`
- **API Dependencies:** `GET /api/v1/hod/documents`
- **Unauthenticated Access Guard:** Yes (Faculty blocked with 403 / redirect)

#### `/hod/upload` (UploadPage (HOD Scoped))
- **Description:** Upload patents on behalf of department faculty.
- **Allowed Roles:** `hod_admin, super_admin`
- **API Dependencies:** `POST /api/v1/uploads/`
- **Unauthenticated Access Guard:** Yes (Faculty blocked with 403 / redirect)

#### `/hod/duplicates` (HodDuplicatesPage)
- **Description:** Review duplicate detection cases flagged within the department.
- **Allowed Roles:** `hod_admin, super_admin`
- **API Dependencies:** `GET /api/v1/duplicates/`
- **Unauthenticated Access Guard:** Yes (Faculty blocked with 403 / redirect)

#### `/hod/conflicts` (HodConflictsPage)
- **Description:** Review conflicting authorship / ownership claims within department.
- **Allowed Roles:** `hod_admin, super_admin`
- **API Dependencies:** `GET /api/v1/conflicts/`
- **Unauthenticated Access Guard:** Yes (Faculty blocked with 403 / redirect)

#### `/hod/reports` (HodReportsPage)
- **Description:** Department IP analytics, annual trends, publication/grant breakdowns.
- **Allowed Roles:** `hod_admin, super_admin`
- **API Dependencies:** `GET /api/v1/analytics/by-department`, `POST /api/v1/exports/`
- **Unauthenticated Access Guard:** Yes (Faculty blocked with 403 / redirect)

#### `/hod/audit` (HodAuditPage)
- **Description:** Audit trails for actions within the department scope.
- **Allowed Roles:** `hod_admin, super_admin`
- **API Dependencies:** `GET /api/v1/audit/logs`
- **Unauthenticated Access Guard:** Yes (Faculty blocked with 403 / redirect)

#### `/hod/associations` (AssociationsPage (HOD Scoped))
- **Description:** Department-level co-inventor association oversight.
- **Allowed Roles:** `hod_admin, super_admin`
- **API Dependencies:** `GET /api/v1/associations/`
- **Unauthenticated Access Guard:** Yes (Faculty blocked with 403 / redirect)

#### `/hod/profile` (FacultyProfilePage (HOD Profile))
- **Description:** HOD personal profile and administrative credentials.
- **Allowed Roles:** `hod_admin, super_admin`
- **API Dependencies:** `GET /api/v1/faculty/profile`
- **Unauthenticated Access Guard:** Yes (Faculty blocked with 403 / redirect)

#### `/admin/dashboard` (AdminDashboardPage)
- **Description:** Institution-wide IP analytics, system health, user counts, queue throughput.
- **Allowed Roles:** `super_admin`
- **API Dependencies:** `GET /api/v1/admin/dashboard`, `GET /api/v1/admin/dashboard/activity`
- **Unauthenticated Access Guard:** Yes (HOD & Faculty blocked with 403 / redirect)

#### `/admin/faculty` (AdminFacultyPage)
- **Description:** Manage all faculty and HOD accounts, assign departments, toggle status, create users.
- **Allowed Roles:** `super_admin`
- **API Dependencies:** `GET /api/v1/admin/faculty`, `POST /api/v1/admin/faculty`, `PATCH /api/v1/admin/faculty/{id}`
- **Unauthenticated Access Guard:** Yes (HOD & Faculty blocked with 403 / redirect)

#### `/admin/granted-patents` (AdminGrantedPatentsPage)
- **Description:** Institutional registry of granted patents and certified designs, grant date filters.
- **Allowed Roles:** `super_admin`
- **API Dependencies:** `GET /api/v1/admin/ip-records?workflow_state=GRANTED`
- **Unauthenticated Access Guard:** Yes (HOD & Faculty blocked with 403 / redirect)

#### `/admin/patent-upload` (UploadPage (Super Admin))
- **Description:** Administrative bulk / single document ingestion.
- **Allowed Roles:** `super_admin`
- **API Dependencies:** `POST /api/v1/uploads/`
- **Unauthenticated Access Guard:** Yes (HOD & Faculty blocked with 403 / redirect)

#### `/admin/ip-records` (AdminRecordsPage)
- **Description:** All institutional IP records, advanced filters (department, status, type, year).
- **Allowed Roles:** `super_admin`
- **API Dependencies:** `GET /api/v1/admin/ip-records`
- **Unauthenticated Access Guard:** Yes (HOD & Faculty blocked with 403 / redirect)

#### `/admin/master-records` (AdminMasterRecordsPage)
- **Description:** Master deduplicated IP entities across multi-faculty claims.
- **Allowed Roles:** `super_admin`
- **API Dependencies:** `GET /api/v1/admin/master-ip-records`
- **Unauthenticated Access Guard:** Yes (HOD & Faculty blocked with 403 / redirect)

#### `/admin/queues` (AdminQueuesPage)
- **Description:** Background processing queues (OCR, Extraction, Verification, Identity Resolution).
- **Allowed Roles:** `super_admin`
- **API Dependencies:** `GET /api/v1/admin/queues/status`, `GET /api/v1/admin/queues/verifications`
- **Unauthenticated Access Guard:** Yes (HOD & Faculty blocked with 403 / redirect)

#### `/admin/reports` (AdminReportsPage)
- **Description:** Executive reports generation, export to CSV/Excel/PDF, NAAC/NIRF reporting.
- **Allowed Roles:** `super_admin`
- **API Dependencies:** `GET /api/v1/analytics/overview`, `POST /api/v1/exports/`
- **Unauthenticated Access Guard:** Yes (HOD & Faculty blocked with 403 / redirect)

#### `/admin/excel-import` (AdminExcelImportPage)
- **Description:** Batch import legacy patent records from Excel spreadsheets with schema validation.
- **Allowed Roles:** `super_admin`
- **API Dependencies:** `POST /api/v1/admin/excel-import/preview`, `POST /api/v1/admin/excel-import/import`
- **Unauthenticated Access Guard:** Yes (HOD & Faculty blocked with 403 / redirect)

#### `/admin/audit` (AdminAuditPage)
- **Description:** Comprehensive institutional audit log viewer, security events, actor IP & timestamp.
- **Allowed Roles:** `super_admin`
- **API Dependencies:** `GET /api/v1/admin/audit-logs`, `GET /api/v1/admin/security-events`
- **Unauthenticated Access Guard:** Yes (HOD & Faculty blocked with 403 / redirect)

#### `/admin/settings` (AdminSettingsPage)
- **Description:** Institutional configuration, departments & designations management, storage quotas.
- **Allowed Roles:** `super_admin`
- **API Dependencies:** `GET /api/v1/admin/departments`, `POST /api/v1/admin/departments`, `GET /api/v1/admin/designations`
- **Unauthenticated Access Guard:** Yes (HOD & Faculty blocked with 403 / redirect)

---

## 2. Backend API Endpoint Inventory (97 Endpoints, 109 Operations)

| Method | Endpoint Path | Tag | Auth Requirement | Required Role / Perm | Status Codes | Automated Test Coverage |
| :---: | :--- | :--- | :---: | :---: | :---: | :---: |
| `GET` | `/` | `general` | None (Public) | `Public` | `200` | **COVERED** |
| `GET` | `/api/v1/admin/associations` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/admin/conflicts` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/admin/conflicts/{conflict_id}/assign` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/admin/conflicts/{conflict_id}/resolve` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/admin/dashboard` | `admin` | Bearer JWT / Cookie | `super_admin` | `200` | **COVERED** |
| `GET` | `/api/v1/admin/dashboard/activity` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/admin/departments` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/admin/departments` | `admin` | Bearer JWT / Cookie | `super_admin` | `201` | **COVERED** |
| `PATCH` | `/api/v1/admin/departments/{dept_id}` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `DELETE` | `/api/v1/admin/departments/{dept_id}` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/admin/designations` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/admin/designations` | `admin` | Bearer JWT / Cookie | `super_admin` | `201` | **COVERED** |
| `PATCH` | `/api/v1/admin/designations/{desg_id}` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `DELETE` | `/api/v1/admin/designations/{desg_id}` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/admin/duplicates` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/admin/duplicates/{case_id}/resolve` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/admin/excel-import/import` | `excel-import` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/admin/excel-import/preview` | `excel-import` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/admin/faculty` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/admin/faculty` | `admin` | Bearer JWT / Cookie | `super_admin` | `201` | **COVERED** |
| `GET` | `/api/v1/admin/faculty/{faculty_id}` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `PATCH` | `/api/v1/admin/faculty/{faculty_id}` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `DELETE` | `/api/v1/admin/faculty/{faculty_id}` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/admin/faculty/{faculty_id}/activate` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/admin/faculty/{faculty_id}/deactivate` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/admin/faculty/{faculty_id}/reset-credentials` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/admin/ip-records` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/admin/ip-records/{record_id}` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `PATCH` | `/api/v1/admin/ip-records/{record_id}` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/admin/ip-records/{record_id}/grant` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/admin/master-ip-records` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/admin/queues/associations` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/admin/queues/conflicts` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/admin/queues/verifications` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/admin/reports/pending-associations` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/admin/settings` | `admin` | Bearer JWT / Cookie | `super_admin` | `200` | **COVERED** |
| `PATCH` | `/api/v1/admin/settings` | `admin` | Bearer JWT / Cookie | `super_admin` | `200` | **COVERED** |
| `GET` | `/api/v1/admin/verifications` | `admin` | Bearer JWT / Cookie | `super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/analytics/by-department` | `analytics` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/analytics/by-faculty` | `analytics` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/analytics/overview` | `analytics` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/analytics/trends` | `analytics` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/associations/` | `associations` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/associations/` | `associations` | Bearer JWT / Cookie | `Authenticated` | `201, 422` | **COVERED** |
| `GET` | `/api/v1/associations/pending` | `associations` | Bearer JWT / Cookie | `Authenticated` | `200` | **COVERED** |
| `POST` | `/api/v1/associations/send-all` | `associations` | Bearer JWT / Cookie | `Authenticated` | `200` | **COVERED** |
| `POST` | `/api/v1/associations/{request_id}/cancel` | `associations` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/associations/{request_id}/clarify` | `associations` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/associations/{request_id}/respond` | `associations` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/audit/` | `audit` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/audit/logs` | `audit` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/audit/security-events` | `audit` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/audit/stats` | `audit` | Bearer JWT / Cookie | `Authenticated` | `200` | **COVERED** |
| `POST` | `/api/v1/auth/csrf` | `auth` | Bearer JWT / Cookie | `Authenticated` | `200` | **COVERED** |
| `POST` | `/api/v1/auth/forgot-password` | `auth` | None / Credential | `Anonymous / User` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/auth/login` | `auth` | None / Credential | `Anonymous / User` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/auth/logout` | `auth` | Bearer JWT / Cookie | `Authenticated` | `200` | **COVERED** |
| `GET` | `/api/v1/auth/me` | `auth` | Bearer JWT / Cookie | `Authenticated` | `200` | **COVERED** |
| `POST` | `/api/v1/auth/refresh` | `auth` | None / Credential | `Anonymous / User` | `200` | **COVERED** |
| `POST` | `/api/v1/auth/reset-password` | `auth` | None / Credential | `Anonymous / User` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/conflicts/` | `conflicts` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/conflicts/{conflict_id}/resolve` | `conflicts` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/duplicates/` | `duplicates` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/duplicates/{case_id}/resolve` | `duplicates` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/exports/` | `exports` | Bearer JWT / Cookie | `Authenticated` | `202, 422` | **COVERED** |
| `GET` | `/api/v1/exports/{job_id}` | `exports` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/exports/{job_id}/download` | `exports` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/faculty/dashboard` | `faculty` | Bearer JWT / Cookie | `faculty, hod_admin, super_admin` | `200` | **COVERED** |
| `GET` | `/api/v1/faculty/history` | `faculty` | Bearer JWT / Cookie | `faculty, hod_admin, super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/faculty/my-records` | `faculty` | Bearer JWT / Cookie | `faculty, hod_admin, super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/faculty/profile` | `faculty` | Bearer JWT / Cookie | `faculty, hod_admin, super_admin` | `200` | **COVERED** |
| `POST` | `/api/v1/faculty/upload` | `faculty` | Bearer JWT / Cookie | `faculty, hod_admin, super_admin` | `202, 422` | **COVERED** |
| `POST` | `/api/v1/faculty/{record_id}/associate/{other_faculty_id}` | `faculty` | Bearer JWT / Cookie | `faculty, hod_admin, super_admin` | `201, 422` | **COVERED** |
| `POST` | `/api/v1/faculty/{record_id}/contributors/{contributor_id}/review` | `faculty` | Bearer JWT / Cookie | `faculty, hod_admin, super_admin` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/faculty/{record_id}/request-verification` | `faculty` | Bearer JWT / Cookie | `faculty, hod_admin, super_admin` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/faculty/{record_id}/review` | `faculty` | Bearer JWT / Cookie | `faculty, hod_admin, super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/faculty/{record_id}/status` | `faculty` | Bearer JWT / Cookie | `faculty, hod_admin, super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/hod/audit` | `hod` | Bearer JWT / Cookie | `hod_admin, super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/hod/conflicts` | `hod` | Bearer JWT / Cookie | `hod_admin, super_admin` | `200` | **COVERED** |
| `GET` | `/api/v1/hod/dashboard` | `hod` | Bearer JWT / Cookie | `hod_admin, super_admin` | `200` | **COVERED** |
| `GET` | `/api/v1/hod/documents` | `hod` | Bearer JWT / Cookie | `hod_admin, super_admin` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/hod/duplicates` | `hod` | Bearer JWT / Cookie | `hod_admin, super_admin` | `200` | **COVERED** |
| `GET` | `/api/v1/hod/faculty` | `hod` | Bearer JWT / Cookie | `hod_admin, super_admin` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/hod/reminders` | `hod` | Bearer JWT / Cookie | `hod_admin, super_admin` | `200` | **COVERED** |
| `GET` | `/api/v1/hod/reports` | `hod` | Bearer JWT / Cookie | `hod_admin, super_admin` | `200` | **COVERED** |
| `GET` | `/api/v1/ip-records/` | `ip-records` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/ip-records/{record_id}` | `ip-records` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `PATCH` | `/api/v1/ip-records/{record_id}` | `ip-records` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/ip-records/{record_id}/file` | `ip-records` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/notifications/` | `notifications` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/notifications/read-all` | `notifications` | Bearer JWT / Cookie | `Authenticated` | `200` | **COVERED** |
| `GET` | `/api/v1/notifications/unread-count` | `notifications` | Bearer JWT / Cookie | `Authenticated` | `200` | **COVERED** |
| `DELETE` | `/api/v1/notifications/{notification_id}` | `notifications` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/notifications/{notification_id}/read` | `notifications` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/search/` | `search` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/search/suggestions` | `search` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/uploads/` | `uploads` | Bearer JWT / Cookie | `Authenticated` | `202, 422` | **COVERED** |
| `GET` | `/api/v1/uploads/config` | `uploads` | Bearer JWT / Cookie | `Authenticated` | `200` | **COVERED** |
| `GET` | `/api/v1/uploads/{ip_record_id}/status` | `uploads` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/verification/attempts` | `verification` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/verification/attempts/{attempt_id}` | `verification` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/verification/attempts/{attempt_id}/retry` | `verification` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/verification/initiate/{record_id}` | `verification` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `GET` | `/api/v1/verification/institutional/{record_id}` | `verification` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/verification/institutional/{record_id}` | `verification` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/verification/pipeline/requeue-stalled` | `verification` | Bearer JWT / Cookie | `Authenticated` | `200` | **COVERED** |
| `GET` | `/api/v1/verification/sources` | `verification` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
| `POST` | `/api/v1/verification/verify` | `verification` | Bearer JWT / Cookie | `Authenticated` | `200, 422` | **COVERED** |
