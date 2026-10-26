# FPP Role-Permission Matrix & Access Control Audit

**Execution Date:** 2026-10-26  
**Audited System:** Faculty Patent Collection and Verification Portal (FPP)  
**Roles Discovered in Codebase:**
1. **Super Admin (`super_admin`):** Institutional administrator with full visibility, faculty management, department governance, master record resolution, queue oversight, system settings, and exports.
2. **Department HOD (`hod_admin`):** Department head with oversight of department-scoped faculty, document reviews, duplicate/conflict cases within department, departmental exports, and department audit trails.
3. **Faculty (`faculty`):** Individual researcher/inventor with personal dashboard, document uploads, personal records management, co-inventor association acceptance/rejection, profile editing, and notifications.
4. **Anonymous / Unauthenticated (`anonymous`):** Public visitor restricted strictly to login (`/login`), password reset deep-linking (`/reset?token=...`), and health probes (`/healthz`, `/readyz`).

---

## 1. Comprehensive Role-Permission Matrix

| Action / Capability | Anonymous | Faculty | Department HOD (`hod_admin`) | Super Admin (`super_admin`) | Frontend Guard Mechanism | Backend Guard Dependency / Filter |
| :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| **Login (`POST /api/v1/auth/login`)** | Allowed | Allowed | Allowed | Allowed | Public route | Rate-limited credential check |
| **Logout (`POST /api/v1/auth/logout`)** | Denied (401) | Allowed | Allowed | Allowed | UI navigation menu | Session cookie revocation |
| **Session Restoration (`GET /api/v1/auth/me`)** | Denied (401) | Allowed | Allowed | Allowed | `AuthProvider` on app mount | `get_current_user` JWT validation |
| **Token Refresh (`POST /api/v1/auth/refresh`)** | Denied (401) | Allowed | Allowed | Allowed | `client.ts` Axios/Fetch interceptor | Refresh token signature & type validation |
| **Password Reset Request (`POST /api/v1/auth/forgot-password`)** | Allowed | Allowed | Allowed | Allowed | Forgot password modal on `/login` | Rate-limited email dispatch |
| **Password Reset Execution (`POST /api/v1/auth/reset-password`)** | Allowed | Allowed | Allowed | Allowed | `/reset?token=...` UI page | One-time token validation & invalidation |
| **Faculty Dashboard (`/faculty/dashboard`)** | Redirect | Allowed | Allowed | Allowed | `ProtectedRoute` | `GET /api/v1/faculty/dashboard` (`require_faculty`) |
| **Upload Patent Document (`/faculty/upload`)** | Redirect | Allowed | Allowed | Allowed | `ProtectedRoute` | `POST /api/v1/uploads/` (`require_faculty`) |
| **View Personal Records (`/faculty/records`)** | Redirect | Allowed (Own) | Allowed (Own) | Allowed (Own) | `ProtectedRoute` | `GET /api/v1/faculty/my-records` (Scoped to user_id) |
| **View Record Details (`/faculty/records/:id`)** | Redirect | Allowed (Own/Assoc) | Allowed (Dept) | Allowed (All) | `ProtectedRoute` | `GET /api/v1/ip-records/{id}` (Ownership check) |
| **Edit Record Draft Metadata** | Redirect | Allowed (Draft/Own) | Denied (Read-only) | Allowed (Admin override)| `RecordDetailPage` UI condition | `PATCH /api/v1/ip-records/{id}` (Ownership/Role) |
| **Initiate Co-Inventor Association** | Redirect | Allowed | Allowed | Allowed | `RecordDetailPage` association modal | `POST /api/v1/associations/` (`require_faculty`) |
| **Respond to Association (Accept/Reject)** | Redirect | Allowed (Target) | Allowed (Target) | Allowed (Admin override)| `AssociationsPage` | `POST /api/v1/associations/{id}/respond` |
| **View Notifications (`/notifications`)** | Redirect | Allowed (Own) | Allowed (Own) | Allowed (Own) | `ProtectedRoute` | `GET /api/v1/notifications/` (Scoped to user_id) |
| **Global IP Search (`/search`)** | Redirect | Allowed | Allowed | Allowed | `ProtectedRoute` | `GET /api/v1/search/` (`require_faculty`) |
| **HOD Dashboard (`/hod/dashboard`)** | Redirect | Denied (403/Redirect) | Allowed (Dept) | Allowed (Global) | `RequireRole(['hod_admin', 'super_admin'])` | `GET /api/v1/hod/dashboard` (`require_hod_admin`) |
| **HOD View Dept Faculty (`/hod/faculty`)** | Redirect | Denied (403/Redirect) | Allowed (Dept) | Allowed (Global) | `RequireRole(['hod_admin', 'super_admin'])` | `GET /api/v1/hod/faculty` (`require_department_scope`) |
| **HOD Document Verification (`/hod/documents`)** | Redirect | Denied (403/Redirect) | Allowed (Dept) | Allowed (Global) | `RequireRole(['hod_admin', 'super_admin'])` | `GET /api/v1/hod/documents` (`require_department_scope`) |
| **HOD Duplicates Review (`/hod/duplicates`)** | Redirect | Denied (403/Redirect) | Allowed (Dept) | Allowed (Global) | `RequireRole(['hod_admin', 'super_admin'])` | `GET /api/v1/duplicates/` (`require_hod_admin`) |
| **HOD Conflicts Review (`/hod/conflicts`)** | Redirect | Denied (403/Redirect) | Allowed (Dept) | Allowed (Global) | `RequireRole(['hod_admin', 'super_admin'])` | `GET /api/v1/conflicts/` (`require_hod_admin`) |
| **HOD Reports & Analytics (`/hod/reports`)** | Redirect | Denied (403/Redirect) | Allowed (Dept) | Allowed (Global) | `RequireRole(['hod_admin', 'super_admin'])` | `GET /api/v1/analytics/by-department` |
| **HOD Audit Log Viewer (`/hod/audit`)** | Redirect | Denied (403/Redirect) | Allowed (Dept) | Allowed (Global) | `RequireRole(['hod_admin', 'super_admin'])` | `GET /api/v1/audit/logs` (`require_department_scope`) |
| **Admin Dashboard (`/admin/dashboard`)** | Redirect | Denied (403/Redirect) | Denied (403/Redirect) | Allowed | `RequireRole(['super_admin'])` | `GET /api/v1/admin/dashboard` (`require_super_admin`) |
| **Manage Faculty & HODs (`/admin/faculty`)** | Redirect | Denied (403/Redirect) | Denied (403/Redirect) | Allowed | `RequireRole(['super_admin'])` | `GET /api/v1/admin/faculty` (`require_super_admin`) |
| **Create Faculty Account** | Redirect | Denied (403/Redirect) | Denied (403/Redirect) | Allowed | `AdminFacultyPage` Add modal | `POST /api/v1/admin/faculty` (`require_super_admin`) |
| **Create / Reassign HOD** | Redirect | Denied (403/Redirect) | Denied (403/Redirect) | Allowed | `AdminFacultyPage` HOD selector | `_ensure_single_active_hod` (409 Conflict check) |
| **Granted Patents Registry (`/admin/granted-patents`)** | Redirect | Denied (403/Redirect) | Denied (403/Redirect) | Allowed | `RequireRole(['super_admin'])` | `GET /api/v1/admin/ip-records?workflow_state=GRANTED` |
| **Master IP Deduplication (`/admin/master-records`)** | Redirect | Denied (403/Redirect) | Denied (403/Redirect) | Allowed | `RequireRole(['super_admin'])` | `GET /api/v1/admin/master-ip-records` (`require_super_admin`) |
| **Background Queue Management (`/admin/queues`)**| Redirect | Denied (403/Redirect) | Denied (403/Redirect) | Allowed | `RequireRole(['super_admin'])` | `GET /api/v1/admin/queues/status` (`require_super_admin`) |
| **Institutional Reports & Exports (`/admin/reports`)**| Redirect | Denied (403/Redirect) | Denied (403/Redirect) | Allowed | `RequireRole(['super_admin'])` | `POST /api/v1/exports/` (`require_super_admin`) |
| **Excel Batch Import (`/admin/excel-import`)** | Redirect | Denied (403/Redirect) | Denied (403/Redirect) | Allowed | `RequireRole(['super_admin'])` | `POST /api/v1/admin/excel-import/import` (`require_super_admin`) |
| **Institutional Audit Logs (`/admin/audit`)** | Redirect | Denied (403/Redirect) | Denied (403/Redirect) | Allowed | `RequireRole(['super_admin'])` | `GET /api/v1/admin/audit-logs` (`require_super_admin`) |
| **System Settings & Depts (`/admin/settings`)** | Redirect | Denied (403/Redirect) | Denied (403/Redirect) | Allowed | `RequireRole(['super_admin'])` | `GET/POST /api/v1/admin/departments` (`require_super_admin`) |

---

## 2. Cross-Department & Cross-User Data Isolation Verification

1. **Department Boundary Enforcement for HODs:**
   - When a user with role `hod_admin` requests `/api/v1/hod/documents` or `/api/v1/hod/faculty`, the backend extracts `current_user['department_id']`.
   - SQL queries append `WHERE user.department_id = :dept_id` or `WHERE ip_record.department_id = :dept_id`.
   - Any attempt by an HOD to request records or faculty belonging to another department returns **HTTP 403 Forbidden** or an empty filtered result set.
2. **Individual Record Isolation for Faculty:**
   - When a user with role `faculty` calls `GET /api/v1/faculty/my-records`, the query explicitly filters on `WHERE ip_record.user_id = :user_id` or confirmed contributor associations.
   - An unassociated faculty member cannot view unpublished draft records of other faculty via direct ID manipulation (`GET /api/v1/ip-records/{other_id}`). The API returns **HTTP 403 / 404**.
3. **Super Admin Scope:**
   - `super_admin` has institutional oversight across all departments, permitted to view global queues, all records, and audit logs.

---

## 3. Defense-in-Depth Verification: Frontend Guard vs. Backend Guard

| Probe Scenario | Frontend Guard Response | Backend Independent Response | Security Conclusion |
| :--- | :--- | :--- | :--- |
| **Anonymous access to `/admin/dashboard`** | `ProtectedRoute` redirects to `/login` | `GET /api/v1/admin/dashboard` returns **HTTP 401 Unauthorized** | **SECURE (Dual Gated)** |
| **Faculty access to `/admin/faculty`** | `RequireRole` redirects to `/` | `GET /api/v1/admin/faculty` returns **HTTP 403 Forbidden** | **SECURE (Dual Gated)** |
| **Faculty access to `/hod/dashboard`** | `RequireRole` redirects to `/` | `GET /api/v1/hod/dashboard` returns **HTTP 403 Forbidden** | **SECURE (Dual Gated)** |
| **HOD access to `/admin/settings`** | `RequireRole` redirects to `/` | `GET /api/v1/admin/departments` returns **HTTP 403 Forbidden** | **SECURE (Dual Gated)** |
| **Tampered JWT (Invalid Signature)** | Interceptor clears state, redirects | Backend returns **HTTP 401 Invalid token** | **SECURE (Cryptographic)** |
| **Refresh token passed as access token** | Interceptor fails auth check | Backend returns **HTTP 401 Invalid token type** | **SECURE (Type Separated)** |

Matrix status: **VERIFIED**. Both frontend UI restrictions and independent backend FastAPI dependencies (`require_super_admin`, `require_hod_admin`, `require_faculty`, `require_department_scope`) enforce strict authorization.
