# FPP Live Production Regression Test Results

**Execution Date:** 2026-10-26  
**Auditor:** QA Automation Engineer & Playwright Specialist  
**Target Environments:**
- Production Frontend: `https://faculty-patent-collection-and-verification-portal.pages.dev`
- Production Backend: `https://faculty-patent-portal-api.onrender.com`

---

## 1. Live Regression Test Execution Summary

A comprehensive regression suite of non-destructive, read-only and reversible tests was executed directly against the live production environment across multiple user roles and views.

| Test Category | Target Endpoint / Page | User Identity | Execution Method | Expected Behavior | Actual Behavior | Result |
| :--- | :--- | :---: | :---: | :--- | :--- | :---: |
| **Public Health** | `GET /healthz` | Anonymous | HTTP GET | Return `{"status":"ok"}` | Status: 200 `{"status":"ok"}` | **PASS** |
| **Public Readiness** | `GET /readyz` | Anonymous | HTTP GET | Return `{"status":"ready"}` | Status: 200 `{"status":"ready"}` | **PASS** |
| **Unauth Gate (Admin)** | `GET /api/v1/admin/dashboard`| Anonymous | HTTP GET | Reject with 401 | Status: 401 Unauthorized | **PASS** |
| **Unauth Gate (HOD)** | `GET /api/v1/hod/dashboard` | Anonymous | HTTP GET | Reject with 401 | Status: 401 Unauthorized | **PASS** |
| **Unauth Gate (Faculty)**| `GET /api/v1/faculty/my-records` | Anonymous | HTTP GET | Reject with 401 | Status: 401 Unauthorized | **PASS** |
| **Admin Login** | `POST /api/v1/auth/login` | Super Admin | HTTP POST | Return 200 + tokens | Status: 200 + JWT + HttpOnly cookies | **PASS** |
| **Admin Dashboard** | `GET /api/v1/admin/dashboard`| Super Admin | HTTP GET | Return 200 + institutional KPIs | Status: 200 (Total records: 18) | **PASS** |
| **Admin Records** | `GET /api/v1/admin/ip-records` | Super Admin | HTTP GET | Return 200 + records list | Status: 200 (18 records returned) | **PASS** |
| **Faculty Login** | `POST /api/v1/auth/login` | Faculty | HTTP POST | Return 200 + tokens | Status: 200 + JWT | **PASS** |
| **Faculty Dashboard** | `GET /api/v1/faculty/dashboard`| Faculty | HTTP GET | Return 200 + personal stats | Status: 200 | **PASS** |
| **Faculty Records** | `GET /api/v1/faculty/my-records` | Faculty | HTTP GET | Return 200 + personal records | Status: 200 | **PASS** |
| **Negative Auth Gate** | `GET /api/v1/admin/dashboard`| Faculty | HTTP GET | Reject with 403 | Status: 403 Forbidden | **PASS** |
| **Token Refresh** | `POST /api/v1/auth/refresh` | Faculty | HTTP POST | Rotate tokens and cookies | Status: 200 + updated tokens | **PASS** |
| **User Logout** | `POST /api/v1/auth/logout` | Faculty | HTTP POST | Revoke session cookies | Status: 200, max-age=0 | **PASS** |
| **Browser Date Display** | `/faculty/records/:id` | Authenticated | Playwright / Browser | Registration & Certificate dates rendered; no invented dates | Reg: `21/05/2025`, Cert: `03/09/2025`, others `—` | **PASS** |
| **Browser Form Modal** | `/admin/faculty` (Add modal) | Super Admin | Playwright / Browser | Inline validation on required fields; modal remains open | Inline validation; zero unwanted redirects | **PASS** |
| **AIDS Dropdown Label**| `/admin/faculty` (Dept select) | Super Admin | Playwright / Browser | Displays canonical label with alias | "Artificial Intelligence and Data Science (AIDS)" | **PASS** |
| **Duplicate HOD Gate** | `POST /api/v1/admin/faculty` | Super Admin | HTTP POST | Reject duplicate active HOD | Status: 409 Conflict (`ACTIVE_HOD_EXISTS`) | **PASS** |

---

## 2. Browser & Visual Verification Evidence

1. **Patent Date Display & Field Isolation:**
   - Record URL: `https://faculty-patent-collection-and-verification-portal.pages.dev/faculty/records/30539176-6ef4-4c25-8aaa-4abfb4c40b48`
   - Verified live in Chrome browser:
     - **Registration Date:** `21/05/2025`
     - **Certificate Issue Date:** `03/09/2025`
     - **Filing Date:** `—` (Not invented)
     - **Grant Date:** `—` (Not invented)
     - **Published Date:** `—` (Not invented)
   - Screenshot artifact: `extracted_info_card_4_1793005687190.png`.
2. **Faculty Creation Modal & Validation:**
   - Navigated live to `/admin/faculty`. Opened "Add faculty" dialog.
   - Submitted empty required fields (`Full name *`, `Official email *`).
   - Browser validation displayed inline required field tooltips. Modal remained open in place, session remained active.
   - Screenshot artifact: `media_1793002159861.png`.

---

## 3. Data Integrity & Safety Confirmation

- **Total Production Records Before Probes:** 18 records.
- **Total Production Records After Probes:** 18 records (Zero deletions, zero mutations).
- **Active HODs Preserved:**
  - Cyber Security: `krishnaselvam35@gamil.com`
  - Artificial Intelligence and Data Science: `qa.aids.hod.live@faculty.edu`
- **Emails Dispatched:** 0 emails.

Live regression verdict: **100% PASS across all tested live workflows.**
