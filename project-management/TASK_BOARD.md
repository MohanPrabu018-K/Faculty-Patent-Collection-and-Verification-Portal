# Autonomous Engineering Task Board

**Single Source of Truth for Project Status & Workstream Ownership**

| Status Values | Description |
|---|---|
| **DONE** | Completed, tested, verified, and accepted |
| **IN_PROGRESS** | Actively being executed |
| **BLOCKED** | Blocked pending client action or external dependency |
| **PLANNED** | Scheduled for execution |

---

## Task List by Workstream

| Task ID | Phase | Title & Description | Owner | Dependencies | Acceptance Criteria | Status |
|---|---|---|---|---|---|---|
| **TSK-001** | Phase 0 | **Git Safety & Working Tree Baseline** | Agent 11 | None | Working tree clean, branches inspected, no forced pushes | **DONE** |
| **TSK-002** | Phase 0 | **Initial Test Suite Baseline Audit** | Agent 8 | TSK-001 | Exact test counts recorded (489 backend, 138 frontend) | **DONE** |
| **TSK-003** | Phase 1 | **Requirements & Role Scoping Gap Analysis** | Agent 2 | TSK-002 | Complete traceability matrix produced (Faculty/HOD/Admin) | **DONE** |
| **TSK-004** | Phase 2 | **₹0 Infrastructure & Account Feasibility Audit** | Agent 12 | TSK-003 | Free-tier quotas verified; personal Google Drive confirmed ₹0 | **DONE** |
| **TSK-005** | Phase 3 | **Google Drive Storage Provider Implementation** | Agent 6 | TSK-004 | `GoogleDriveStorage` with resumable upload, download, retries | **DONE** |
| **TSK-006** | Phase 3 | **Fail-Fast Production Storage Validation** | Agent 5 | TSK-005 | Ephemeral fallback strictly blocked in production | **DONE** |
| **TSK-007** | Phase 3 | **Uploads & PostgreSQL Persistence Wiring** | Agent 5 | TSK-005 | `IpFile.storage_key` (`gdrive/...`) & evidence persisted in DB | **DONE** |
| **TSK-008** | Phase 3 | **Authorized Document Download Streaming** | Agent 5 | TSK-007 | `/api/v1/ip-records/{id}/file` streams bytes; private Drive links hidden | **DONE** |
| **TSK-009** | Phase 3 | **OCR Recovery & Container Wipe Restoration** | Agent 7 | TSK-005 | `requeue_stuck_pipelines` restores wiped files from Drive | **DONE** |
| **TSK-010** | Phase 4 | **Safe Migration Script with SHA-256 Check** | Agent 6 | TSK-007 | `scripts/migrate_storage_to_gdrive.py` with `--dry-run` and rollback | **DONE** |
| **TSK-011** | Phase 4 | **Interactive One-Time OAuth Setup CLI** | Agent 10 | TSK-005 | `scripts/setup_google_drive.py` guides client through token creation | **DONE** |
| **TSK-012** | Phase 5 | **Storage Unit & API Automated Mock Suite** | Agent 8 | TSK-005 | 10 unit/integration tests in `test_gdrive_storage.py` pass | **DONE** |
| **TSK-013** | Phase 5 | **Full Backend & Frontend Regression Suites** | Agent 8 | TSK-012 | 489 backend tests pass; 138 frontend tests pass; 0 build errors | **DONE** |
| **TSK-014** | Phase 6 | **Deployment Runbook & Documentation Updates** | Agent 10 | TSK-011 | `.env.example`, `render.yaml`, `GOOGLE_DRIVE_STORAGE_SETUP.md` updated | **DONE** |
| **TSK-015** | Phase 7 | **GitHub Authoritative Branch Sync** | Agent 11 | TSK-014 | Verified commit `8ae07e3` pushed to `origin/main` | **DONE** |
| **TSK-016** | Phase 7 | **Live Public Health & CDN Inspection** | Agent 10 | TSK-015 | `/healthz` (`{"status":"ok"}`) and Pages CDN verified responding | **DONE** |
| **TSK-017** | Phase 7 | **Client Production Account Setup** | Client / Agent 1 | TSK-016 | Client runs `setup_google_drive.py` and pastes env vars to Render | **BLOCKED (Client Action)** |
| **TSK-018** | Phase 8 | **Final Live End-to-End Verification Gate** | Agent 13 | TSK-017 | Real document upload and retrieval verified on live production | **PLANNED** |
