# FPP Database Cleanup Report — `faculty_portal_staging`

Date: 2026-10-11 | Repository: `E:\Faculty profile portal` (HEAD `8503fe5`, **no commits made**)

## 1. Target database provider and environment

| Item | Value |
|---|---|
| Selected target | `faculty_portal_staging` (local, PostgreSQL 18.4 @ `127.0.0.1:5432`) |
| Migration head | `010` |
| Classification | Local, loopback, disposable — the dedicated staging DB |
| Configured app `DATABASE_URL` | **Neon production** (`ep-…neon.tech`, db `neondb`) — classified only, **never contacted, not modified** |

Credentials and connection strings were never printed.

## 2. Backup confirmation

- `pg_dump -Fc` → `C:\Users\mohan\AppData\Local\Temp\opencode\backup_faculty_portal_staging_20261011_180614.dump`
- Exit 0 · 89 414 bytes · 233 archive entries · SHA256 `80B8402D6694D80A848C44FF33752D19D391B9D4170C2E13B40497919D902BB8`
- Stored in the pre-approved temp directory (non-public, not committed to Git).

## 3. Super Admin preservation status

- **Before cleanup:** the staging DB was **empty** (0 rows in every table) — no Super Admin existed to preserve.
- **Action (documented exception):** created the repo's intended Super Admin identity exactly as specified by `backend/create_test_users.py`:
  - `id=test-admin-001`, `email=admin@faculty.edu`, `full_name=Admin User`, `role=super_admin`,
    `is_active=true`, `status=active`, `faculty_id/department_id/designation_id=NULL`.
- **Password:** generated a fresh Argon2id hash via the app's own `hash_password()`; **verified** with `verify_password()` → `True`. Credentials not exposed. No existing account was modified or reset.

## 4–7. Records deleted by phase

The staging DB contained **no pre-existing application data**, so all deletion categories are **0** (documented, not assumed):

| Category | Deleted |
|---|---|
| Faculty accounts | 0 |
| HOD accounts | 0 |
| Patent / master patent records (`ip_record`, `master_ip_record`) | 0 |
| Contributors (`ip_contributor`, `master_ip_contributor`, `external_contributor`) | 0 |
| Association requests (`association_request`) | 0 |
| Verification records (`verification_attempt`, `master_verification_attempt`) | 0 |
| Duplicate / conflict / identity records (`duplicate_case`, `conflict_case`, `identity_conflict`) | 0 |
| Provenance / snapshot / linkage (`field_provenance`, `faculty_profile_snapshot`, `faculty_ip_association`) | 0 |
| Processing jobs / files (`processing_job`, `ip_file`) | 0 |
| Notifications | 0 |
| Tokens / security events / audit / rate-limit state | 0 |

**Verification-run artifacts (created then removed by exact ID):** 1 temporary faculty account (`cleanup.probe.faculty@staging.invalid`) + 1 `audit_log` row — both deleted after the capability check. Final state: zero trace rows.

## 6. File storage

- Inspected storage config: `STORAGE_BACKEND`, `LOCAL_STORAGE_ROOT`, `MAX_UPLOAD_BYTES`, `MAX_PDF_PAGES` present in `.env`; local files live under `backend/storage`.
- `backend/storage` contains **earlier-QA artifacts** (per-user dirs such as `FAC-*`, `test-*`, UUID dirs with PDFs) with **no ownership mapping to any record in the (empty) staging DB**.
- Per the ownership rule, **no files were deleted**; ownership could not be verified against this empty database. File storage is **NOT claimed clean**.

## 8. Database integrity verification (actual SQL)

- `alembic_version` head: `010` — migration history intact.
- `user`: exactly **1** row — `test-admin-001` / `admin@faculty.edu`, role `super_admin`, `is_active=true`, `status=active`; Argon2id hash verifies.
- `department`: **3** (stg-dept-a/b/c) · `designation`: **2** (stg-desig-professor, stg-desig-hod) — reference data for fresh testing.
- All 20 data tables (`association_request`, `audit_log`, `conflict_case`, `duplicate_case`, `external_contributor`, `faculty_ip_association`, `faculty_profile_snapshot`, `field_provenance`, `identity_conflict`, `ip_contributor`, `ip_file`, `ip_record`, `master_ip_contributor`, `master_ip_record`, `master_verification_attempt`, `notification`, `processing_job`, `rate_limit_state`, `security_event`, `verification_attempt`): **0 rows**.
- Orphaned FK references: `user→department` 0, `user→designation` 0.
- Sequences: **N/A** — schema uses UUID string PKs; no public sequences exist.

## 9. Super Admin login verification (local stack)

Backend run locally against the staging DB only (`DATABASE_URL=postgresql+asyncpg://…faculty_portal_staging`, `APP_ENV=development`, `E2E_TEST=1`, `COOKIE_SECURE=false`, `SCHEDULER_ENABLED=false`; server stopped afterwards, port 8000 free).

| Check | Result |
|---|---|
| POST `/api/v1/auth/login` (admin@faculty.edu) | **200 + csrf token** |
| GET `/api/v1/auth/me` | **200, role=`super_admin`** |
| GET `/api/v1/admin/dashboard` | **200** |
| GET `/api/v1/admin/ip-records` | **200, total=0** (no stale patent/verification data) |
| GET `/api/v1/admin/faculty` | **200, total=0** (no stale faculty/HOD data) |
| GET `/api/v1/analytics/overview` | **200** |
| Create faculty capability (`POST /api/v1/admin/faculty`) | **201** (temp account, then removed by exact ID) |
| Logout → re-login cycle | **200 / 200** |
| Patent-upload auth gate: unauthenticated multipart `POST /api/v1/uploads/` | **400 `CSRF_TOKEN_INVALID`** (middleware rejects before handler; no record possible without session) |

## 10. Remaining record counts and final state

| Table | Rows |
|---|---|
| `user` | **1** (the Super Admin) |
| `department` | 3 |
| `designation` | 2 |
| everything else | **0** on every table |

- FK integrity: **PASS** (no orphans).
- DB connection health: **PASS** (login + admin APIs served).
- No production contact; no commits/pushes/deploys; no secrets in logs or this report.
- Ready for fresh testing with the retained Super Admin (documented test credentials from `backend/create_test_users.py`).

## Unresolved / notes

1. Because the target DB was empty, "clean initial state" required **creating the intended Super Admin account + 3 department + 2 designation reference rows** (approved decision). Listed deletion counts are 0 and documented as such — nothing existed to delete.
2. `backend/storage` artifacts from earlier QA runs were left untouched (unverifiable ownership vs. an empty DB).
3. Pre-existing (unchanged) risk: legacy `backend/create_test_users.py` targets the app `DATABASE_URL` (currently Neon). Do not run it against production; use the staged guard workflow with an explicit staging DSN instead.