"""Real-world HTTP upload verification for Certificate 459641-001.pdf.

Uses an ALREADY-RUNNING backend via the normal API flow (login -> CSRF ->
multipart upload -> BackgroundTasks -> poll to terminal state). No code changes;
read-only against source.

SAFETY (fail closed — required before this may touch a network socket):

* ``STAGING_CONFIRM=1`` must be set: this script performs a REAL upload and
  only ever targets an explicitly confirmed non-production stack.
* ``STAGING_API_URL`` must be set to the running backend's base URL. Loopback is
  always allowed; the known production hosts (and ``.pages.dev`` /
  ``.onrender.com`` namespaces) are refused; any other remote host must be
  listed in ``STAGING_ALLOWED_HOSTS``. There is no default target.
* The running backend itself must be connected to a disposable database — that
  is the operator's responsibility; this script only guarantees the address it
  talks to is confirmed + non-production.

Example (PowerShell, from repo root):

    $env:STAGING_CONFIRM="1"
    $env:STAGING_API_URL="http://127.0.0.1:8000"
    python scripts/verify_real_upload_459641.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent / "staging"))
import guard  # noqa: E402

EMAIL = "test@faculty.edu"
PASSWORD = "TestPass123!"
PDF = r"C:\Users\mohan\Downloads\New folder (2)\Certificate 459641-001.pdf"
TERMINAL = {"COMPLETED", "COMPLETED_WITH_ERRORS", "AWAITING_REVIEW", "FAILED"}


def main() -> int:
    base_url = guard.resolve_staging_api_url()
    with httpx.Client(base_url=base_url, timeout=60) as c:
        # 1. Real login
        r = c.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
        print("LOGIN", r.status_code)
        if r.status_code != 200:
            print(r.text)
            return 1
        csrf = r.json()["csrf_token"]
        c.cookies.update(r.cookies)

        # 2. Real CSRF token present
        print("CSRF_TOKEN", "yes" if csrf else "no")

        # 3. Real multipart upload
        with open(PDF, "rb") as fh:
            r = c.post(
                "/api/v1/uploads/",
                files={"file": ("Certificate 459641-001.pdf", fh, "application/pdf")},
                headers={"X-CSRF-Token": csrf},
            )
        print("UPLOAD", r.status_code)
        if r.status_code not in (200, 202):
            print(r.text)
            return 1
        body = r.json()
        record_id = body["ip_record_id"]
        print("RECORD_ID", record_id)

        # 4. Poll to terminal state
        status_body = None
        for attempt in range(90):
            r = c.get(f"/api/v1/uploads/{record_id}/status", headers={"X-CSRF-Token": csrf})
            if r.status_code != 200:
                print("POLL_ERROR", r.status_code, r.text)
                return 1
            status_body = r.json()
            ps = status_body["processing_status"]
            print(f"  poll {attempt}: {ps}")
            if ps in TERMINAL:
                break
            time.sleep(1)

        print("\n=== FINAL STATUS ===")
        for k in (
            "ip_type",
            "design_number",
            "serial_number",
            "registration_date",
            "processing_status",
            "verification_status",
            "patent_number",
            "title",
            "applicant",
        ):
            print(f"  {k}: {status_body.get(k)}")

        print("  jobs:")
        for j in status_body["jobs"]:
            print(f"    - {j['job_type']:16} {j['status']:22} err={j['error_message']}")

        return 0


if __name__ == "__main__":
    raise SystemExit(main())
