"""Real-world HTTP upload verification for Certificate 459641-001.pdf.

Uses the already-running backend at http://localhost:8000 via the normal API
flow (login -> CSRF -> multipart upload -> BackgroundTasks -> poll to terminal
state). No code changes; read-only against source.
"""
from __future__ import annotations

import time

import httpx

BASE = "http://localhost:8000"
EMAIL = "test@faculty.edu"
PASSWORD = "TestPass123!"
PDF = r"C:\Users\mohan\Downloads\New folder (2)\Certificate 459641-001.pdf"
TERMINAL = {"COMPLETED", "COMPLETED_WITH_ERRORS", "AWAITING_REVIEW", "FAILED"}


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=60) as c:
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
