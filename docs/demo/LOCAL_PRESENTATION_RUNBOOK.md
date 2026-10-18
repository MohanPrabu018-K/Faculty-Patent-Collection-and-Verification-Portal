# FPP Local Presentation Runbook (one page)

**URLs:** frontend `http://127.0.0.1:5173` · backend `http://127.0.0.1:8099`
**Credentials:** `C:\Users\mohan\AppData\Local\Temp\opencode\fpp-demo\demo_credentials.txt`
(DO NOT COMMIT · DO NOT SCREENSHOT · Super Admin uses the documented seed login)

## Start (if not running)
Backend: `cd 'E:\Faculty profile portal'`
`$env:DATABASE_URL='postgresql+asyncpg://postgres@localhost:5432/faculty_portal_staging'; $env:APP_ENV='development'; $env:DEBUG='true'; $env:COOKIE_SECURE='false'; $env:LOCAL_STORAGE_ROOT='E:/Faculty profile portal/backend/storage'; $env:PORT='8099'; $env:E2E_TEST='1'; backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8099 --log-level warning`
Frontend: `cd 'E:\Faculty profile portal\frontend'`
`$env:VITE_API_BASE_URL='http://127.0.0.1:8099/api/v1'; node_modules\.bin\vite.cmd --port 5173 --host 127.0.0.1`
Restart the frontend if pages ever fail to load (dev server expired once during prep).

## Show order (~20 min)
1. Super Admin login → dashboard (counts, queues).
2. Faculty/department structure (Admin → Faculty; Computing/Electronics/Mechanical).
3. Faculty A login → upload `fpp-demo\files\demo-live.pdf` (fresh upload, watch status).
4. ASSOC record → auto-associated uploader, no self-request; Send Association Request → 2 pending.
5. Faculty B login → associations → incoming pending (Accept live on stage, or leave pending).
6. HOD A/B/C logins → documents: all see Multidept; only A sees Assoc; none sees pre-stage Review; no Approve/Reject anywhere.
7. Conflict record → blocked status; attempt Grant as Super Admin → refused 422 (use CONFLICT record, NOT the ready one).
8. GRANT-READY record → Grant Patent → Confirm → GRANTED (the live moment).
9. Granted listing + audit trail (Admin → Audit).
10. Review record → failed-safe, no fabricated data.
11. Notifications bell, search, reports; resize to phone width for responsive UI.

## Recovery
- Accidental live grant on the wrong record: cannot be undone in-app (terminal by design) — say so, move on.
- Mutated demo data: re-run `demo_seed.py` + `demo_flows.py` (idempotent; needs `STAGING_ADMIN_PASS`), then `freeze.py` to re-verify.
- Backend DB is `faculty_portal_staging` (verified). Backup: `fpp-demo\backup_staging_20261013_2202.dump` (+sha256). Production Neon never touched.

## Known limitations (say upfront if asked)
- Reset-password emails: honestly unavailable locally (503, no provider configured) — by design, not a bug.
- Font loads from Google CDN; offline rooms fall back to system fonts.
- Four legacy exact-flow browser suites need a harness that doesn't exist (equivalent coverage: staging + demo specs).
