"""Real end-to-end check of the FastAPI BackgroundTasks document pipeline.

Launches a real uvicorn server (no Celery / Redis), then:
  login -> csrf -> POST /api/v1/uploads/ (real PDF) -> BackgroundTasks runs the
  deterministic 11-agent orchestrator -> persists to PostgreSQL ->
  GET /api/v1/uploads/{id}/status shows a terminal processing_status.

Requires: PostgreSQL up, test users seeded (create_test_users.py), OCR.Space key
configured in .env. Run from repo root:
    python scripts/e2e_backgroundtasks_pipeline.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
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
    assert PDF.exists(), f"missing test PDF: {PDF}"
    env = {**os.environ, "PYTHONPATH": str(BACKEND)}
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
