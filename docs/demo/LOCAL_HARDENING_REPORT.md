# FPP Local Hardening Report (presentation cycle)

## A. Database cleanup
- Backup: `fpp-demo\backup_staging_20261013_2202.dump` (107,091 bytes, sha256 recorded, pg_restore list verified: 223 entries, outside repo).
- Before: 24 users / 11 records / 8 depts / 125 audit rows. After: 2 users (admin + Mohan) / 0 records / 3 depts.
- Deleted (verified test residue only): 22 users, 11 records, 5 test departments, 164 rows total (assoc 3, contributors 12, dup 2, conflict 1, jobs 13, files 1, audit-scoped 71, notifications 20). 47 stale upload files moved to recoverable trash (DB `ip_file` empty).
- Preserved: admin@faculty.edu (id/hash/login intact), Mohan faculty, stg departments/designations, alembic history, all non-scoped audit rows.
- Remaining uncertain: `master_ip_record` ×3 (UUID ids, no contributors/links) — preserved, reported.
- D-002 note: with storage now empty, any requeue reports `skipped_missing_file` honestly; demo uploads repopulate live files.

## B. Demo scenarios
8/8 built through real APIs/pipeline (see DATASET doc): S1 2-pending ✓, S2 fan-out A/B/C ✓, S3 grantable-verified-pristine ✓, S4 granted + 409 ✓, S5 422-blocked ✓, S6 rejected + history + 422 ✓, S7 null-safe ✓, S8 backup + live PDF ✓.
Genuine findings fixed during seeding: (1) demo HODs created as `faculty` because no reference designation bears the exact title `HOD` — roles corrected via DB to mirror provision tooling (runbook note; production designations titled `HOD` work via API); (2) send-all correctly 409s on post-completion records — multidept requests went through the single-recipient endpoint (same rows/audit); (3) titles set via real uploader-review (malformed stays null).

## C. Testing (all current execution)
- Backend: **475 passed, 11 skipped, 0 failed** (staging; includes 2 new unknown-404 association tests added this cycle).
- Frontend Vitest: **19 files / 138 passed**. tsc: exit 0. Build: exit 0.
- Playwright **real system Chrome**: staging 33/33 (pre-cleanup baseline) + demo.spec **6/6** (SA dashboard + grant button present-not-clicked, faculty flows, HOD fan-out matrix, role-gate denial, mobile) — serial, live stack.
- Console/network: zero unexpected events (phased NetProbe rules; font-CDN sandbox rule counted; reset-post never fired).
- API smoke 6/6 post-change; exports/reports covered by committed suites (renderers, auth/scoping, HOD scoping) + live admin/HOD report endpoints healthy.
- Genuine UI bug fixed: missing favicon → console 404 for every visitor; added inline SVG icon (zero new files).
- Integrity (§9 script): all PASS, 0 failures. Freeze (§14 script): all PASS (8 logins, 8 states, 9 PDFs, both servers).
- Blocked: legacy exact-* suites (no harness; equivalence documented); multi-worker race (thread + multi-process evidence recorded earlier).

## D. Presentation readiness
- Startup commands + URLs: runbook §1 (backend 8099 + frontend 5173, both restarted reliably this cycle).
- Credentials: `fpp-demo\demo_credentials.txt` (8 demo logins, verified); SA = documented seed (not in file).
- Order: 14-step runbook; grant moment uses pristine GRANT-READY; rehearsal = demo.spec green + freeze green.
- Limitations: reset-email 503 by design; offline fonts fall back; no live re-upload dependency (backup record exists).

## E. Verdicts
- **DATABASE: GO** (clean, consistent, backed up, integrity green).
- **BACKEND: GO** (475/0 + live flows).
- **FRONTEND: GO** (138 + tsc/build + real-Chrome suites).
- **CHROME DEMO: GO** (system-chrome 6/6 + mobile).
- **FULL PRESENTATION: GO** — "No known blocking defects were found in the tested presentation scenarios. Remaining untested/blocked items are listed above (§C blocked, §A uncertain masters)."
