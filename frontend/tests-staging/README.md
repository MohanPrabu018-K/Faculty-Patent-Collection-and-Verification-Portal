# Staging authenticated E2E suite (rules A–F)

Runs the authenticated release-rule matrix against a **disposable staging or
local** stack. It is deliberately separate from `frontend/tests/` (which targets
shared/dev servers) and refuses to run against production.

## Prerequisites

1. A provisioned staging dataset:
   ```powershell
   $env:STAGING_DATABASE_URL='postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/faculty_portal_staging'
   python scripts/staging/provision_staging.py --create-database --migrate
   ```
2. The staging stack running (the config has **no** `webServer`):
   * backend: `uvicorn app.main:app --port 8000` with `DATABASE_URL` = staging
     DB, `APP_ENV=development`, `COOKIE_SECURE=false`, `CORS_ORIGINS=http://localhost:5173`,
     `E2E_TEST=1` (widens the login rate limit for parallel logins).
   * frontend: `npm run dev` with `VITE_API_BASE_URL=http://localhost:8000/api/v1`.

## Run

```powershell
$env:STAGING_CONFIRM='1'
$env:STAGING_FRONTEND_URL='http://localhost:5173'
$env:STAGING_API_URL='http://localhost:8000'
cd frontend
npx playwright test -c playwright-staging.config.ts
```

Guard-only (no servers required):

```powershell
npx playwright test -c playwright-staging.config.ts 00-guard.spec.ts
```

## Files

| file | purpose |
| --- | --- |
| `guard.ts` | fail-closed env resolution (unit-tested by `00-guard.spec.ts`) |
| `fixtures.ts` | loads `.staging-fixtures.json` (written by provisioning) |
| `client.ts` | `StagingClient` — real HTTP + bearer/CSRF handling |
| `00-guard.spec.ts` | guard self-checks (no network) |
| `scenarios.spec.ts` | the A–F rule matrix |

## Rule → test map

| rule | tests |
| --- | --- |
| A — uploader auto-association, no self-request, idempotent send-all | A1, A2 |
| B — uploader-only sending, HOD not a recipient, duplicate 409, IDOR 403, recipient accept | B1–B5 |
| C — external contributors excluded | C1 |
| D — HOD strictly read-only + department scoping | D1–D5 |
| E — Super Admin grant gates + duplicate/conflict resolution | E0–E7 |
| F — RBAC, CSRF, deactivation, audit, UI redirect | F1–F5 |

## Cleanup

```powershell
python scripts/staging/teardown_staging.py          # report
python scripts/staging/teardown_staging.py --yes    # delete stg- rows only
```
