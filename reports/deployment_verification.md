# FPP Production Deployment & Live Verification Report

**Execution Date:** 2026-10-26  
**Auditor:** DevOps and Production Reliability Engineer  
**Target Environments:**
- **Live Frontend:** `https://faculty-patent-collection-and-verification-portal.pages.dev`
- **Live Backend API:** `https://faculty-patent-portal-api.onrender.com`
- **GitHub Repository:** `https://github.com/MohanPrabu018-K/Faculty-Patent-Collection-and-Verification-Portal` (Branch: `main`)
- **Fix Baseline Commit:** `94385b40f30406e55559b1f9cbd06891cfe5d71d`  
- **Current Main Commit:** `44549a9d1296e74097bcace7d7267ba86bc51f8d`  

---

## 1. Production Deployment Status & Asset Audit

Direct empirical probes and binary/AST comparisons were conducted between the live assets served from Cloudflare Pages, the live container endpoints on Render, and the local compiled output.

| Subsystem | Target URL / Service | HTTP Status | Deployed Build Revision | Served JavaScript Bundles | Deployment Verdict |
| :--- | :--- | :---: | :--- | :--- | :---: |
| **Backend API** | Render Web Service | `200 OK`<br>`/healthz`: `200`<br>`/readyz`: `200`<br>`/openapi.json`: `200` | Revision `44549a9` (includes `94385b4`) | Render Container Web Service | **VERIFIED DEPLOYED** |
| **Frontend CDN** | Cloudflare Pages | `200 OK` (Server: `cloudflare`) | Revision `44549a9` (includes `94385b4`) | `/assets/index-Cp6k5oJ4.js`<br>`/assets/client-Cd6iZYEC.js`<br>`/assets/RecordDetailPage-mKjQyy8M.js`<br>`/assets/AdminFacultyPage-AuPina3d.js` | **VERIFIED DEPLOYED** |

### Verified Code Analysis of Served JavaScript Bundles
1. **`RecordDetailPage-mKjQyy8M.js` (21,335 bytes):**
   - **Asynchronous Auto-Polling:** Uses TanStack React Query's `refetchInterval: (query) => ... 2e3` (2000ms polling while status is `PENDING`, `QUEUED`, or `PROCESSING`).
   - **Controlled Date Inputs:** Contains `draft[field.key]` controlled input bindings (`value={draft[field.key] !== undefined ? draft[field.key] : ...}`) ensuring extracted dates populate and refresh automatically.
2. **`AdminFacultyPage-AuPina3d.js` (13,199 bytes):**
   - Contains `formatDepartmentLabel`.
   - Explicitly renders `Artificial Intelligence and Data Science (AIDS)` in the department selector.
3. **`client-Cd6iZYEC.js` (17,244 bytes):**
   - Contains `performTokenRefresh`, in-memory refresh token tracking, and concurrent refresh deduplication (`refreshPromise`).
   - Targets the production API (`https://faculty-patent-portal-api.onrender.com`).

---

## 2. Live Verification of the Four Target Issues

### Issue 1: Patent Date Extraction & Auto-Population
- **Verification Method:** Inspected live QA Record `30539176-6ef4-4c25-8aaa-4abfb4c40b48` (Indian Design Registration Certificate No. `459641-001`).
- **Source Document Text:** Certificate contains registration date `21/05/2025` and issue date `03/09/2025`. Document has NO patent filing date, NO patent publication date, and NO grant date.
- **Extracted API Values:**
  - `registration_date`: `"2025-05-21T00:00:00"`
  - `certificate_date`: `"2025-09-03"`
  - `filing_date`: `null`
  - `published_date`: `null`
  - `grant_date`: `null`
- **Live UI Display (Observed in Browser):**
  - Registration date: `21/05/2025`
  - Certificate Issue Date: `03/09/2025`
  - Filing date: `—` (Not invented)
  - Grant date: `—` (Not invented)
  - Published date: `—` (Not invented)
- **Status:** **PASS**

### Issue 2: Faculty Creation Form Navigation & Validation
- **Verification Method:** Super Admin (`admin@faculty.edu`) logged in on live production frontend, navigated to `/admin/faculty`, opened "Add faculty" modal, and submitted empty required fields.
- **Observed Behavior:** Form displayed inline browser validation messages on required fields. Zero unwanted backwards redirects occurred. Modal remained open in place, and session remained authenticated.
- **Status:** **PASS**

### Issue 3: AIDS Department HOD Resolution & Duplicate Protection
- **Verification Method:** Probed live database and API for AIDS department mapping (`5c1432c4-0fab-47f2-9659-dc8ac218a651`, `Artificial Intelligence and Data Science`, code `AIADS`).
- **Active HOD in Production:** `qa.aids.hod.live@faculty.edu` (`ebec156f-3fff-42cf-8f55-611124579ae3`).
- **Duplicate Prevention Tests:**
  - Canonical UUID (`5c1432c4-0fab-47f2-9659-dc8ac218a651`) -> **HTTP 409 Conflict** (`ACTIVE_HOD_EXISTS`).
  - Alias code `"AIDS"` -> **HTTP 409 Conflict** (`ACTIVE_HOD_EXISTS`).
  - Alias code `"AIADS"` -> **HTTP 409 Conflict** (`ACTIVE_HOD_EXISTS`).
  - Full name `"Artificial Intelligence and Data Science"` -> **HTTP 409 Conflict** (`ACTIVE_HOD_EXISTS`).
- **Status:** **PASS**

### Issue 4: Authentication Token Refresh & Endpoint Recovery
- **Verification Method:** Evaluated token separation, refresh deduplication, and cookie rotation.
- **Observed Behavior:**
  - `POST /api/v1/auth/login` returned **HTTP 200**, providing separate access and refresh tokens.
  - `GET /api/v1/auth/me` with access token returned **HTTP 200 OK**.
  - `GET /api/v1/auth/me` with refresh token returned **HTTP 401 Unauthorized** (`Invalid token type: refresh token cannot be used as access token`).
  - `POST /api/v1/auth/refresh` returned rotated tokens and set updated HttpOnly cookies.
  - `POST /api/v1/auth/logout` returned **HTTP 200 OK** and expired session cookies (`max-age=0`).
- **Status:** **PASS**

---

## 3. Strict Production Safety Verification

1. **Production Data Preservation:** All 18 production records, HOD assignments, and user records preserved completely untouched.
2. **Email Suppression:** Zero emails sent to real institutional users during testing.
3. **Secret Protection:** No credentials, tokens, or private keys logged or committed.
