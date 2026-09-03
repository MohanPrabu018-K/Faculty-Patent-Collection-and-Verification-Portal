# Faculty Patent & Design Portal — Workflow Compliance Audit

Audit date: 2026-09-01 · Mode: read-only inspection (no code changed)
Services observed live: backend `http://localhost:8000`, frontend `http://localhost:5173`

---

## SECTION 1 — PROJECT OVERVIEW

| Concern | Implementation |
| ------- | -------------- |
| Architecture | Monolith FastAPI backend + React SPA frontend; deterministic 11-agent pipeline run via FastAPI `BackgroundTasks` (Celery/Redis removed) |
| Frontend | React 19 + TypeScript + Vite + TanStack Query + React Hook Form + Zod + lucide-react |
| Backend | FastAPI + SQLAlchemy 2.0 (async + sync) + Pydantic Settings + structlog |
| Database | PostgreSQL (Neon, TLS) via `asyncpg`; SQLAlchemy `declarative_base()` models in [`base.py`](backend/app/models/base.py:8) |
| Authentication | JWT (HS256) in httpOnly cookie + CSRF double-submit cookie; Argon2id password hashing |
| OCR | **External free API — OCR.Space** (NOT local/open-source). Base64 image POST in [`ocr_pipeline.py`](backend/app/services/ocr_pipeline.py:139) |
| QR | pyzbar + OpenCV QRCodeDetector in [`decode_qr_payloads()`](backend/app/services/ocr_pipeline.py:395) |
| IP verification | `IndiaPatentOfficeAdapter` (configurable JSON endpoint, disabled by default) + `ManualVerificationAdapter` + **mock** `PatentOfficeMockAdapter` for US/EP/JP/CN |
| Background processing | FastAPI `BackgroundTasks` → [`run_document_pipeline()`](backend/app/workers/orchestrator_task.py:18) |
| Storage | Local filesystem (`LOCAL_STORAGE_ROOT=./storage`) |
| Major modules | 11 agents, orchestrator, services (ocr, extraction, identity, duplicate, association, notifications, search/analytics), API routers, security middleware |

---

## SECTION 2 — COMPLETE REQUIREMENT MATRIX

| # | Requirement | Status | Existing Implementation | File/Module | Missing/Issue |
| - | ----------- | ------ | ----------------------- | ----------- | ------------- |
| 1 | Super Admin faculty master DB | 🟡 PARTIAL | `User` + `Department` + `Designation` tables; admin can create faculty | [`admin.py`](backend/app/api/admin.py:146) | No dept/designation on `User`, no joining details, credentials generated as empty hash |
| 2 | Faculty upload PDF/image + validation | 🟡 PARTIAL | Upload + extension/size/magic-byte validation | [`uploads.py`](backend/app/api/uploads.py:27) | No readability check, no pre-processing duplicate/type check |
| 3 | QR detect + decode + retrieve identifier | 🟡 PARTIAL | QR decode via pyzbar/OpenCV | [`ocr_pipeline.py`](backend/app/services/ocr_pipeline.py:395) | Only decodes payload; no official-record retrieval |
| 4 | Local/open-source OCR fallback | ⚠️ INCORRECT | OCR.Space external API | [`ocr_pipeline.py`](backend/app/services/ocr_pipeline.py:139) | Not local; paid-free but external dependency; regex-only field extraction |
| 5 | Official IP India verification | 🟡 PARTIAL | `IndiaPatentOfficeAdapter` (disabled) | [`adapters.py`](backend/app/verification/adapters.py:389) | Disabled by default; no real InPASS scraping; no Google discovery layer |
| 6 | Certificate vs official comparison → conflict | 🟡 PARTIAL | Field confidence + MISMATCH status | [`adapters.py`](backend/app/verification/adapters.py:508) | Mismatch does NOT create a ConflictCase |
| 7 | External verification failure fallback | ✅ FULLY | `ManualVerificationAdapter` → VERIFICATION_REQUIRED | [`adapters.py`](backend/app/verification/adapters.py:167) | Works gracefully |
| 8 | Faculty identity matching engine | ⚠️ INCORRECT | Name similarity + variants + institution match | [`identity_resolution.py`](backend/app/services/identity_resolution.py:95) | Agent uses mock faculty DB, never queries real `User` table |
| 9 | Contributor classification (internal/external/unknown) | ❌ NOT IMPLEMENTED | `IpContributor.is_external` column only | [`base.py`](backend/app/models/base.py:200) | No agent/logic populates contributor rows |
| 10 | Same-name faculty handling | 🟡 PARTIAL | `IdentityConflict` model + same-name conflict flag | [`faculty_identity_agent.py`](backend/app/agents/faculty_identity_agent.py:110) | Not persisted, no UI candidate selection |
| 11 | Uploader review screen + field provenance | ❌ NOT IMPLEMENTED | Upload → "Open record" | [`UploadPage.tsx`](frontend/src/features/faculty/UploadPage.tsx:17) | No review screen, no field source/status editing |
| 12 | Faculty Profile Derived data | ❌ NOT IMPLEMENTED | — | — | No provenance "Faculty Profile Derived" anywhere |
| 13 | Contributor association workflow | 🟡 PARTIAL | AssociationRequest create/respond | [`associations.py`](backend/app/api/associations.py:39) | No contributor-selection UI; no primary-owner logic |
| 14 | Faculty association request + approval states | 🟡 PARTIAL | PENDING/APPROVED/REJECTED/CLARIFICATION_REQUESTED | [`associations.py`](backend/app/api/associations.py:56) | Missing "Not Me" action, no notification, no reminders, no admin escalation, no record linkage (model lacks `record_id`) |
| 15 | Duplicate detection (prevent master dup) | ⚠️ INCORRECT | `DuplicateDetectionService` exists | [`duplicate_detection.py`](backend/app/services/duplicate_detection.py:183) | Agent gets empty `existing_records`; fingerprint never stored on upload; no real detection |
| 16 | Different versions of same IP → one master | ❌ NOT IMPLEMENTED | — | — | Each upload = new `IpRecord`; no master grouping |
| 17 | Final verification engine | 🟡 PARTIAL | VerificationAgent sets status | [`verification_agent.py`](backend/app/agents/verification_agent.py:8) | No comprehensive final gate; no NEEDS_REVIEW state |
| 18 | One master record + per-association status | ❌ NOT IMPLEMENTED | — | — | No master record table |
| 19 | Supporting documents + history persistence | 🟡 PARTIAL | `IpFile` linked to `IpRecord` | [`base.py`](backend/app/models/base.py:222) | No association history/confirmation/audit persisted per record |
| 20 | Super Admin dashboard metrics | 🟡 PARTIAL | 9 KPIs | [`admin.py`](backend/app/api/admin.py:41) | Missing duplicates, external contributors, OCR/verification failures, dept/faculty-wise |
| 21 | Advanced combined admin filters | 🟡 PARTIAL | ip-records: type/status/dept/faculty/date | [`admin.py`](backend/app/api/admin.py:286) | Missing designation, number, title, author position, conflict type, confidence, internal/external; no combined UI |
| 22 | Conflict Center | 🟡 PARTIAL | `ConflictCase` + admin conflicts queue | [`admin.py`](backend/app/api/admin.py:94) | Conflicts not auto-created for most triggers |
| 23 | Audit log (immutable) | ❌ NOT IMPLEMENTED | `log_audit` → console only | [`logging.py`](backend/app/core/logging.py:19) | Audit API returns empty placeholder; `AuditLog` table never written |
| 24 | Faculty deactivation preserves records | ✅ FULLY | `deactivate` sets `is_active=False` | [`admin.py`](backend/app/api/admin.py:196) | Records reference user id, not cascade-deleted |
| 25 | Historical department preservation | ❌ NOT IMPLEMENTED | `IpRecord.department_id` FK | [`base.py`](backend/app/models/base.py:144) | Dynamic; no historical snapshot |
| 26 | Controlled verification states | 🟡 PARTIAL | UNVERIFIED/VERIFICATION_REQUIRED/VERIFIED/MISMATCH | [`base.py`](backend/app/models/base.py:21) | Missing NEEDS_REVIEW, POOR_OCR, NO_RESPONSE, EXTERNAL_FAILURE states |
| 27 | Complete end-to-end ₹0-cost workflow | ❌ NOT IMPLEMENTED | Fragments only | — | Many disconnected stages; not achievable end-to-end |

---

## SECTION 3 — FULLY IMPLEMENTED (genuinely working end-to-end)

1. **Authentication (login → cookie → /me)** — [`auth.py`](backend/app/api/auth.py:67) issues JWT + CSRF cookies; [`deps.py`](backend/app/api/deps.py:18) accepts cookie fallback; frontend [`client.ts`](frontend/src/api/client.ts:28) sends credentials. Verified live: `POST /auth/login 200`, `GET /auth/me 200`.
2. **Role-based authorization** — [`require_super_admin`](backend/app/api/deps.py:94) + [`RequireRole`](frontend/src/app/ProtectedRoute.tsx) gate admin routes. Verified live.
3. **File upload + storage + validation** — [`uploads.py`](backend/app/api/uploads.py:27) validates extension, size, magic bytes, writes local file, creates `IpRecord`/`IpFile`/`ProcessingJob`, returns 202. Verified live (202 Accepted).
4. **External verification failure fallback** — [`ManualVerificationAdapter`](backend/app/verification/adapters.py:167) always returns `VERIFICATION_REQUIRED`; IP India adapter degrades gracefully when disabled.
5. **Faculty deactivation without record deletion** — [`deactivate_faculty`](backend/app/api/admin.py:196).

---

## SECTION 4 — PARTIALLY IMPLEMENTED

- **Faculty master DB (#1):** `create_faculty` exists but stores `password_hash=body.get("password_hash","")` (empty), no department/designation/joining fields, no credential generation flow.
- **Upload validation (#2):** extension/size/magic-byte validation done; readability, pre-duplicate, and pre-type checks absent.
- **QR (#3):** decode works (pyzbar+OpenCV), but no identifier retrieval/verification from the decoded payload.
- **IP India verification (#5):** adapter is real but disabled (`IPINDIA_ENABLED=false`, empty URL); mock adapters hard-code fake records.
- **Certificate vs official comparison (#6):** field-level confidence + `MISMATCH` status computed, but mismatch never creates a `ConflictCase`.
- **Same-name handling (#10):** conflict detected in-memory, never persisted to `IdentityConflict`, no UI.
- **Association workflow (#13/#14):** create/respond endpoints work, but "Not Me" missing, no notifications, no reminders, no admin review escalation, no `record_id` linkage.
- **Duplicate detection (#15):** service + fingerprint helpers exist, but agent is fed empty `existing_records` and fingerprint is never persisted on upload.
- **Final verification (#17):** single-agent status set, no multi-rule gate, no `NEEDS_REVIEW` enum.
- **Admin dashboard (#20):** 9 KPIs only; missing many required metrics.
- **Advanced filters (#21):** partial query params; no designation/title/author-position/conflict/confidence/internal-external, no combined UI.
- **Conflict Center (#22):** queue + resolve exist, but conflicts aren't auto-generated for most triggers.
- **Controlled states (#26):** partial enum; missing NEEDS_REVIEW / POOR_OCR / NO_RESPONSE / EXTERNAL_FAILURE.

---

## SECTION 5 — NOT IMPLEMENTED

- **#9 Contributor classification** — no agent/logic writes `IpContributor` or classifies internal/external/unknown.
- **#11 Uploader review screen** — no UI; extracted data auto-persisted without review or field-level source/status editing.
- **#12 Faculty Profile Derived** — no such provenance/source exists.
- **#16 Different versions → one master IP** — no master record grouping.
- **#18 One master record + per-association verification status** — no master record table; associations don't carry per-record status.
- **#23 Audit log persistence** — `AuditLog` table never written; audit API returns `{"audit_logs": [], "message": "implement..."}`.
- **#25 Historical department preservation** — no snapshot table; department is a live FK.
- **#27 Complete end-to-end workflow** — not achievable with current gaps.

---

## SECTION 6 — INCORRECT IMPLEMENTATIONS

1. **OCR is not local (#4).** Requirement: "Local/Open Source OCR", "avoid paid Google OCR". Implementation uses OCR.Space external API (free but external), not Tesseract/PyMuPDF local OCR. [`ocr_pipeline.py`](backend/app/services/ocr_pipeline.py:139).
2. **Faculty identity matching uses mock data (#8).** `FacultyIdentityResolutionAgent` calls `IdentityResolutionService.match_institution(...)` which falls back to `_get_mock_faculty_db()` (hard-coded names), never queries the real `User` table. [`faculty_identity_agent.py`](backend/app/agents/faculty_identity_agent.py:55), [`identity_resolution.py`](backend/app/services/identity_resolution.py:240).
3. **Duplicate detection is non-functional end-to-end (#15).** Agent receives `existing_records = context.get("existing_records", [])` (always empty), and `IpFile.fingerprint` is never computed/stored on upload, so `check_duplicate_by_fingerprint` can never match. [`duplicate_detection_agent.py`](backend/app/agents/duplicate_detection_agent.py:67), [`uploads.py`](backend/app/api/uploads.py:86).
4. **Association model lacks `record_id`.** The dataclass `AssociationRequest` in the service has `record_id`, but the DB model `AssociationRequest` in [`base.py`](backend/app/models/base.py:304) has **no** `record_id` column — so an association can never be linked to a master IP record.
5. **Audit log returns placeholders.** [`notifications_audit.py`](backend/app/api/notifications_audit.py:59) and [`audit.py`](backend/app/api/audit.py:20) return empty arrays with "implement DB queries".

---

## SECTION 7 — BROKEN / BLOCKED FEATURES

1. **🔴 Real upload pipeline crash — serial_number UniqueViolation.** Observed live in backend log: `duplicate key value violates unique constraint "ix_ip_record_serial_number"` during `run_document_pipeline`. Cause: [`_update_ip_record_from_agents()`](backend/app/workers/orchestrator_task.py:100) blindly writes extracted `serial_number` (and `design_number`) into `IpRecord` where `serial_number` is unique-indexed. Different PDFs can OCR to the same serial, crashing the BackgroundTask and leaving the record in `FAILED`. This blocks real upload processing.
2. **🔴 IP India verification is disabled** (`IPINDIA_ENABLED=false`, empty URL), so official verification never actually runs — all lookups degrade to manual.
3. **🔴 `faculty.py` `/upload` route is a dead redirect** — it reads the file and returns a message telling the caller to use `/api/v1/uploads/` instead; it never persists anything. [`faculty.py`](backend/app/api/faculty.py:99).
4. **🔴 `/api/v1/ip-records` is a placeholder** returning `records: []`. [`ip_records.py`](backend/app/api/ip_records.py:24).
5. **🔴 Audit/notifications/search placeholder routers** return empty data (`audit.py`, `notifications.py`, `search.py`, `analytics.py`, `exports.py`).
6. **🔴 Intermittent `POST /auth/login 400` and `POST /uploads/ 400`** observed in logs — consistent with the CSRF middleware rejecting requests where `X-CSRF-Token`/cookie mismatch; the frontend works but non-browser or stale-CSRF calls are rejected.

---

## SECTION 8 — WORKFLOW GAPS (trace)

Login ✅ → Upload ✅ → Validation 🟡 (no readability/dup/type) → QR ✅ (decode only) → Identifier extraction 🟡 (regex, no QR-derived lookup) → IP India verification 🔴 (disabled) → certificate vs official 🟡 (no conflict creation) → faculty matching 🔴 (mock DB) → contributor classification ❌ → uploader review ❌ → association requests 🟡 (no "Not Me", no notification, no record link) → faculty approval 🟡 → duplicate detection 🔴 (empty data) → final verification 🟡 → master record ❌ → faculty profiles 🟡 → admin dashboard 🟡 → conflict center 🟡 → audit log ❌.

---

## SECTION 9 — DATABASE GAP ANALYSIS

| Item | Status |
| ---- | ------ |
| Faculty master (`User`) | 🟡 Partial (no dept/designation/joining) |
| Patent/Design master record | ❌ Missing |
| Contributors (`IpContributor`) | 🟡 Partial (table exists, never populated) |
| Faculty associations (`AssociationRequest`) | 🟡 Partial (no `record_id`) |
| Association requests | ✅ Existing |
| Verification results (`VerificationAttempt`) | ✅ Existing |
| Field-level provenance | ❌ Missing (only JSON `evidence` blob) |
| Conflicts (`ConflictCase`, `IdentityConflict`) | ✅ Existing (underused) |
| Supporting documents (`IpFile`) | ✅ Existing |
| Audit logs (`AuditLog`) | ❌ Missing (never written) |
| Historical department | ❌ Missing |
| Account status (`is_active`) | ✅ Existing |
| External contributors (`ExternalContributor`) | ✅ Existing (unused) |
| Duplicate fingerprints (`IpFile.fingerprint`) | 🟡 Partial (column exists, never set) |

---

## SECTION 10 — API GAP ANALYSIS

- **Existing & working:** auth (login/logout/refresh/me/csrf), faculty dashboard/my-records/status/associate, uploads POST + status, admin dashboard/faculty CRUD/queues/duplicates/conflicts, associations list/create/respond, duplicates list/resolve, conflicts list/resolve, verification sources/verify/attempts.
- **Existing but incomplete:** admin `/ip-records` (partial filters), `/ip-records/{id}` (minimal), search/analytics/exports (some wired to real service, some not).
- **Existing but incorrect:** `/api/v1/ip-records` (placeholder `[]`), audit (placeholder `[]`), faculty `/upload` (dead redirect).
- **Missing:** contributor classification endpoint, review/confirm endpoint, field-level provenance endpoint, "Not Me" association action, reminders/admin escalation, master record APIs.

---

## SECTION 11 — UI GAP ANALYSIS

**Faculty:** Login ✅ · Dashboard ✅ · Upload ✅ · Document preview ❌ (no preview pane) · Extraction review ❌ · Contributor selection ❌ · Association requests 🟡 (list only, no respond action) · Verification status ✅ (read-only) · Notifications ❌.

**Super Admin:** Dashboard 🟡 (KPIs only) · Faculty management 🟡 (raw JSON dump) · Patent/design management 🟡 (list + read detail) · Conflict Center 🟡 (queue, no filters) · Advanced filters ❌ · Verification review 🟡 · Association review 🟡 (read-only) · Audit logs ❌ · Analytics 🟡 (backend only, no UI).

---

## SECTION 12 — ₹0-COST COMPLIANCE AUDIT

| Dependency | Type | ₹0? |
| ---------- | ---- | --- |
| OCR.Space | External free API | ✅ free (but external, not local) |
| PyMuPDF (`fitz`) | Open-source | ✅ |
| pyzbar / OpenCV | Open-source | ✅ |
| PostgreSQL (Neon) | Managed DB | ⚠️ Neon free tier OK, but not self-hosted |
| IP India adapter | Self-hosted proxy | ✅ (disabled) |
| Mock patent adapters | Hard-coded fake | ✅ (but fake) |
| OLLAMA env vars | Unused | ✅ (optional, not wired) |

Verdict: **₹0-cost is satisfied** (no paid API/Google Cloud), but OCR violates the "local/open-source" requirement and the DB relies on a managed Neon instance.

---

## SECTION 13 — SECURITY & DATA INTEGRITY GAPS

- Auth: JWT cookie + CSRF ✅, Argon2id ✅, role checks ✅.
- **Faculty isolation:** mostly ✅ (my-records/status filter by `uploader_id`), but `/api/v1/ip-records` is a placeholder with no isolation; search endpoint sets faculty_id to current user for faculty ✅.
- **Admin permissions:** `require_super_admin` on admin router ✅.
- File upload security: extension/size/magic-byte ✅, no antivirus (CLAMAV disabled), no image dimension enforcement despite config.
- **Audit integrity:** ❌ no persistent audit log.
- Data modification protection: ❌ admin/faculty PATCHs don't record before/after audit.
- Duplicate prevention: ❌ not effective.
- Historical preservation: ❌ dept not preserved.
- Sensitive data: ⚠️ `.env` contains real Neon DB credentials and OCR key (committed); CSRF cookie non-httpOnly by design.

---

## SECTION 14 — PRODUCTION READINESS

| Area | % |
| ---- | - |
| Architecture | 60% |
| Backend | 55% |
| Frontend | 35% |
| Database | 50% |
| Verification | 30% |
| OCR | 40% (external, regex) |
| QR | 70% |
| IP India integration | 20% (disabled) |
| Matching | 20% (mock) |
| Duplicate detection | 15% |
| Notifications | 20% (in-memory) |
| Admin | 40% |
| Security | 55% |
| Testing | 60% |
| Error handling | 50% |
| Deployment | 40% |

**Overall production readiness: ~35%.**

---

## SECTION 15 — PRIORITY FIX LIST

### 🔴 P0 — Critical (must fix before system can work)
1. **serial_number/design_number UniqueViolation crash** — [`orchestrator_task.py`](backend/app/workers/orchestrator_task.py:100). Remove unique index misuse or stop writing extracted serial/design into unique columns during persistence; create proper ConflictCase instead.
2. **Duplicate detection is dead** — feed real `existing_records` from DB and compute/store `IpFile.fingerprint` on upload.
3. **Faculty matching uses mock DB** — query `User` table.
4. **Audit log persistence** — write `AuditLog` rows in `log_audit`.
5. **`AssociationRequest` model lacks `record_id`** — add FK to `ip_record`.

### 🟠 P1 — High
6. Uploader review screen + field-level provenance.
7. Contributor classification (internal/external/unknown).
8. "Not Me" association action + notification + reminder + admin escalation.
9. Certificate-vs-official mismatch → create ConflictCase.
10. IP India adapter actually enabled/wired to a real free source or explicit proxy.

### 🟡 P2 — Medium
11. Advanced combined admin filters + Conflict Center filters.
12. Master IP record model (dedupe versions/supporting docs).
13. Historical department snapshot.
14. Expand verification status enum (NEEDS_REVIEW, EXTERNAL_FAILURE, etc.).
15. Admin dashboard missing metrics.

### 🟢 P3 — Low
16. Local OCR fallback (Tesseract/PyMuPDF) to satisfy "local/open-source".
17. Replace placeholder routers (`ip_records`, `audit`, `notifications`, `search`, `analytics`, `exports`).
18. Add document preview pane and notification UI.
19. Remove unused mock patent adapters / OLLAMA references.

---

## SECTION 16 — FINAL VERDICT

1. **How much of the expected workflow is implemented?** Approximately **35%** as genuinely working end-to-end; most features exist only as models, services, or stubs.
2. **Fully working:** ~15%.
3. **Partial:** ~45%.
4. **Missing:** ~30%.
5. **Broken/incorrect:** ~10% (plus several placeholder routers).
6. **Biggest gaps:** no uploader review screen, no contributor classification, no real faculty matching (mock), non-functional duplicate detection, no persistent audit log, no master record, IP India verification disabled, OCR is external not local.
7. **Production-ready?** **No.**
8. **Before production:** complete the P0 items (unique-constraint crash, duplicate detection, real faculty matching, audit persistence, association `record_id`), then the P1 workflow items (review screen, contributor classification, "Not Me" + notifications, conflict creation, IP India wiring).
