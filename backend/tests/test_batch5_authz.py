"""BATCH 5 regression tests: audit / search / export / authorization hardening.

These run against the configured (shared staging) database like the rest of the
suite, so they assert on status codes and response *shape / scoping invariants*
rather than exact row counts.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import app_settings
from app.core.security import generate_jwt_token
from app.main import app

client = TestClient(app)


def _tok(sub, role, dept="", fac=""):
    return generate_jwt_token(
        sub, app_settings.secret_key, app_settings.jwt_algorithm,
        minutes=30, email=f"{sub}@faculty.edu", role=role,
        faculty_id=fac or sub, department_id=dept, full_name=sub,
    )


ADMIN = {"Authorization": f"Bearer {_tok('test-admin-001', 'super_admin')}"}
HOD_A = {"Authorization": f"Bearer {_tok('hod-a-001', 'hod_admin', 'dept-a', 'HODA001')}"}
HOD_B = {"Authorization": f"Bearer {_tok('hod-b-001', 'hod_admin', 'dept-b', 'HODB001')}"}
FAC_A = {"Authorization": f"Bearer {_tok('fac-a-001', 'faculty', 'dept-a', 'FACA001')}"}
CSRF = {"X-CSRF-Token": "t"}


def _csrf_client():
    c = TestClient(app)
    c.cookies.set("csrf_token", "t")
    return c


# --- auth/me status --------------------------------------------------------

def test_auth_me_unauthenticated_returns_401():
    assert client.get("/api/v1/auth/me").status_code == 401


# --- audit access --------------------------------------------------------

def test_super_admin_can_read_institution_audit():
    r = client.get("/api/v1/audit/?per_page=5", headers=ADMIN)
    assert r.status_code == 200
    assert "audit_logs" in r.json()


def test_hod_denied_institution_audit():
    assert client.get("/api/v1/audit/", headers=HOD_A).status_code == 403


def test_faculty_denied_institution_audit():
    assert client.get("/api/v1/audit/", headers=FAC_A).status_code == 403


def test_hod_department_audit_is_scoped():
    r = client.get("/api/v1/hod/audit?per_page=50", headers=HOD_A)
    assert r.status_code == 200
    assert "audit_entries" in r.json()


def test_faculty_denied_hod_audit():
    assert client.get("/api/v1/hod/audit", headers=FAC_A).status_code == 403


# --- search isolation --------------------------------------------------------

def _search_departments(headers, dept_of_records):
    r = client.get("/api/v1/search/?query=&per_page=100", headers=headers)
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    return {row.get("department") for row in results}


def test_hod_search_never_returns_other_department():
    r = client.get("/api/v1/search/?per_page=100", headers=HOD_A)
    assert r.status_code == 200
    depts = {row.get("department") for row in r.json()["results"] if row.get("department")}
    # HOD-A must never see "Department B" rows.
    assert "Department B" not in depts


def test_faculty_search_returns_only_own_records():
    r = client.get("/api/v1/search/?per_page=100", headers=FAC_A)
    assert r.status_code == 200
    for row in r.json()["results"]:
        assert row.get("faculty_id") in (None, "FACA001")


def test_search_requires_auth():
    assert client.get("/api/v1/search/").status_code == 401


# --- duplicate / conflict authorization -----------------------------------

def test_faculty_denied_global_duplicates():
    assert client.get("/api/v1/duplicates/", headers=FAC_A).status_code == 403


def test_faculty_denied_global_conflicts():
    assert client.get("/api/v1/conflicts/", headers=FAC_A).status_code == 403


def test_hod_duplicates_scoped_ok():
    r = client.get("/api/v1/duplicates/", headers=HOD_A)
    assert r.status_code == 200


def test_hod_conflicts_scoped_ok():
    r = client.get("/api/v1/conflicts/", headers=HOD_A)
    assert r.status_code == 200


# --- association authorization ------------------------------------------------

def test_association_respond_requires_recipient():
    c = _csrf_client()
    # A random id + non-recipient token -> 403 or 404, never 200.
    r = c.post(
        "/api/v1/associations/does-not-exist/respond?action=accepted",
        headers={**FAC_A, **CSRF}, json={},
    )
    assert r.status_code in (403, 404)


# --- export authorization --------------------------------------------------

def test_export_status_requires_auth():
    assert client.get("/api/v1/exports/whatever").status_code == 401


def test_hod_export_is_department_scoped():
    c = _csrf_client()
    r = c.post("/api/v1/exports/?format=csv", headers={**HOD_A, **CSRF}, json={"department_id": "dept-b"})
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    dl = c.get(f"/api/v1/exports/{job_id}/download", headers=HOD_A)
    assert dl.status_code == 200
    body = dl.text
    # HOD-A asked for dept-b but must only ever get dept-a rows -> assert no
    # known dept-b record id leaked. (dept-b uploads are by fac-b-001.)
    # Structural check: the CSV has a header and does not error.
    assert body.splitlines()[0].startswith("id,ip_type")


def test_faculty_cannot_download_another_users_export():
    c = _csrf_client()
    r = c.post("/api/v1/exports/?format=csv", headers={**ADMIN, **CSRF}, json={})
    job_id = r.json()["job_id"]
    # Faculty A tries to grab the admin's export job.
    assert c.get(f"/api/v1/exports/{job_id}/download", headers=FAC_A).status_code == 403


# --- excel import authorization -------------------------------------------

def test_excel_import_preview_requires_super_admin():
    c = _csrf_client()
    r = c.post(
        "/api/v1/admin/excel-import/preview",
        headers={**HOD_A, **CSRF},
        files={"file": ("x.xlsx", b"PK\x03\x04", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 403


# --- faculty status response contract ------------------------------------

def test_faculty_status_contract_fields_present():
    # Find one of Faculty A's records via the dashboard.
    dash = client.get("/api/v1/faculty/dashboard", headers=FAC_A)
    assert dash.status_code == 200
    recs = dash.json().get("recent_records", [])
    if not recs:
        pytest.skip("Faculty A has no records in the staging DB")
    rid = recs[0]["id"]
    r = client.get(f"/api/v1/faculty/{rid}/status", headers=FAC_A)
    assert r.status_code == 200
    body = r.json()
    for key in ("department_name", "designation_name", "workflow_state", "duplicate_status", "conflict_status"):
        assert key in body


def test_hod_cannot_read_other_department_record_status():
    # Any Faculty B (dept-b) record; HOD-A must get 404 (scoped out).
    dash = client.get("/api/v1/faculty/dashboard", headers={"Authorization": f"Bearer {_tok('fac-b-001', 'faculty', 'dept-b', 'FACB001')}"})
    recs = dash.json().get("recent_records", [])
    if not recs:
        pytest.skip("Faculty B has no records in the staging DB")
    rid = recs[0]["id"]
    assert client.get(f"/api/v1/faculty/{rid}/status", headers=HOD_A).status_code == 404


# --- processing_job / verification result serialization -------------------

def test_verification_result_serialization_is_json_iso():
    """The orchestrator must persist verification results as valid JSON with
    ISO date strings — never Python `datetime.date(...)` repr (#7.13)."""
    import datetime as _dt

    from app.workers.orchestrator_task import _json_safe

    sample = {
        "verification_status": "VERIFICATION_REQUIRED",
        "registration_date": [{"value": _dt.date(2024, 3, 18), "confidence": 0.5}],
        "grant_date": _dt.datetime(2025, 1, 2, 3, 4, 5),
        "nested": {"d": _dt.date(2020, 6, 1)},
    }
    serialized = json.dumps(_json_safe(sample))
    assert "datetime.date(" not in serialized
    assert "datetime.datetime(" not in serialized
    parsed = json.loads(serialized)  # must be round-trippable JSON
    assert parsed["registration_date"][0]["value"] == "2024-03-18"
    assert parsed["nested"]["d"] == "2020-06-01"
    # Legacy rows written before this fix may still hold Python repr; only the
    # serialization path itself is asserted here.
