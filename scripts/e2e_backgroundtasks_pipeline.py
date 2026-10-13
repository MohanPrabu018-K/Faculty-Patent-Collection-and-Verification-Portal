"""Real end-to-end check of the FastAPI BackgroundTasks document pipeline.

Launches a real uvicorn server (no Celery / Redis), then:
  login -> csrf -> POST /api/v1/uploads/ (real PDF) -> BackgroundTasks runs the
  deterministic 11-agent orchestrator -> persists to PostgreSQL ->
  GET /api/v1/uploads/{id}/status shows a terminal processing_status.

SAFETY (fail closed — required before anything runs):

* ``STAGING_CONFIRM=1`` must be set: this script performs real upload + DB
  writes and may only ever target a disposable test/staging stack.
* ``STAGING_DATABASE_URL`` must be set to an explicit disposable PostgreSQL
  target (validated by ``scripts/staging/guard.py``; loopback allowed). The
  application ``DATABASE_URL`` and the root ``.env`` are NEVER consulted.
* The spawned uvicorn subprocess receives a sandboxed environment: the
  validated staging URL is pinned as ``DATABASE_URL`` (so the app's ``.env``
  value cannot leak into the child), remote-opt-in/allowlist tokens are
  stripped, and non-production run flags (``APP_ENV=development``,
  ``E2E_TEST=1``, ``SCHEDULER_ENABLED=false``, ``COOKIE_SECURE=false``) apply.

Example (cmd.exe / PowerShell, from repo root):

    $env:STAGING_CONFIRM="1"
    $env:STAGING_DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/faculty_portal_staging"
    python scripts/e2e_backgroundtasks_pipeline.py

Requires: disposable PostgreSQL up, test users seeded (create_test_users.py),
local stack from repo root unless overridden. Run from repo root.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR / "staging"))
import guard  # noqa: E402

PDF = BACKEND / "test_patent.pdf"
PORT = 8099
BASE = f"http://127.0.0.1:{PORT}"
EMAIL = "test@faculty.edu"
PASSWORD = "TestPass123!"
TERMINAL = {"COMPLETED", "COMPLETED_WITH_ERRORS", "AWAITING_REVIEW", "FAILED"}


def _wait_health(proc: subprocess.Popen, timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            r = httpx.get(f"{BASE}/healthz", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            time.sleep(0.5)
    return False


def main() -> int:
    # Fail closed BEFORE any side effect: explicit confirmation + a validated,
    # disposable PostgreSQL target. Never falls back to DATABASE_URL / app .env.
    guard.require_staging_confirm("scripts/e2e_backgroundtasks_pipeline.py")
    staging_db_url = guard.resolve_staging_database_url()
    assert PDF.exists(), f"missing test PDF: {PDF}"
    env = guard.sandboxed_backend_env(staging_db_url, backend_dir=str(BACKEND))
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        cwd=str(BACKEND), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        if not _wait_health(proc):
            print("server did not become healthy")
            print(proc.stdout.read() if proc.stdout else "")
            return 1
        print("server healthy on", BASE)

        with httpx.Client(base_url=BASE, timeout=30) as c:
            r = c.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
            print("login:", r.status_code)
            if r.status_code != 200:
                print(r.text)
                return 1
            csrf = r.json()["csrf_token"]
            c.cookies.update(r.cookies)

            with PDF.open("rb") as fh:
                r = c.post(
                    "/api/v1/uploads/",
                    files={"file": ("test_patent.pdf", fh, "application/pdf")},
                    headers={"X-CSRF-Token": csrf},
                )
            print("upload:", r.status_code, r.json())
            if r.status_code not in (200, 202):
                return 1
            record_id = r.json()["ip_record_id"]

            status_body = None
            for attempt in range(40):
                r = c.get(f"/api/v1/uploads/{record_id}/status", headers={"X-CSRF-Token": csrf})
                if r.status_code != 200:
                    print("status poll error:", r.status_code, r.text)
                    return 1
                status_body = r.json()
                ps = status_body["processing_status"]
                print(f"  poll {attempt}: processing_status={ps}")
                if ps in TERMINAL:
                    break
                time.sleep(1)

        print("\n=== FINAL STATUS ===")
        for k in ("processing_status", "verification_status", "ip_type", "patent_number", "title", "applicant"):
            print(f"  {k}: {status_body.get(k)}")
        print("  jobs:")
        for j in status_body["jobs"]:
            print(f"    - {j['job_type']:14} {j['status']:22} err={j['error_message']}")

        ps = status_body["processing_status"]
        job_types = {j["job_type"] for j in status_body["jobs"]}
        ok = ps in TERMINAL and ps != "FAILED" and len(job_types) >= 11
        print("\nRESULT:", "PASS" if ok else "FAIL", f"(status={ps}, distinct_jobs={len(job_types)})")
        return 0 if ok else 2
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
