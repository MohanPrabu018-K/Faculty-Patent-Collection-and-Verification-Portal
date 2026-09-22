"""Regression tests for the GRANTED filter (Issue 4).

Root cause: the granted-patents page sent ?verification_status=GRANTED, but
verification_status is a Postgres ENUM without GRANTED, so the query raised
InvalidTextRepresentationError -> 500 INTERNAL_ERROR. GRANTED lives on
workflow_state (a free String column).

Covers: GRANTED via workflow_state, VERIFIED, existing filters, invalid enum
values (422, never 500), pagination with GRANTED, empty GRANTED result, and
granted-row field completeness. All read-only GETs.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.config import app_settings
from app.core.security import generate_jwt_token
from app.main import app

RECORD_A = "7be9f118-ba87-462a-8d72-c98b688c6aa4"


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def _tok(sub, role, dept="", fac=""):
    return generate_jwt_token(
        sub, app_settings.secret_key, app_settings.jwt_algorithm,
        minutes=30, email=f"{sub}@faculty.edu", role=role,
        faculty_id=fac or sub, department_id=dept, full_name=sub,
    )


ADMIN = {"Authorization": f"Bearer {_tok('test-admin-002', 'super_admin')}"}


def _h(client, auth):
    token = client.cookies.get("csrf_token")
    if token is None:
        token = "t"
        client.cookies.set("csrf_token", token)
    headers = dict(auth)
    headers["X-CSRF-Token"] = token
    return headers


def test_granted_workflow_filter_returns_granted_records(client):
    r = client.get("/api/v1/admin/ip-records?workflow_state=GRANTED", headers=_h(client, ADMIN))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    assert len(body["records"]) >= 1
    for row in body["records"]:
        assert row["workflow_state"] == "GRANTED"


def test_granted_workflow_filter_includes_known_granted_record(client):
    r = client.get("/api/v1/admin/ip-records?workflow_state=GRANTED&per_page=100", headers=_h(client, ADMIN))
    assert r.status_code == 200, r.text
    ids = [row["id"] for row in r.json()["records"]]
    assert RECORD_A in ids


def test_granted_record_row_carries_relevant_fields(client):
    r = client.get("/api/v1/admin/ip-records?workflow_state=GRANTED&per_page=100", headers=_h(client, ADMIN))
    assert r.status_code == 200, r.text
    row = next(row for row in r.json()["records"] if row["id"] == RECORD_A)
    for key in ("id", "ip_type", "title", "verification_status", "processing_status", "workflow_state"):
        assert key in row, f"granted row missing {key}"
    assert row["workflow_state"] == "GRANTED"


def test_verified_filter_still_works(client):
    r = client.get("/api/v1/admin/ip-records?verification_status=VERIFIED", headers=_h(client, ADMIN))
    assert r.status_code == 200, r.text
    for row in r.json()["records"]:
        assert row["verification_status"] == "VERIFIED"


def test_existing_filters_still_work(client):
    for params in (
        "?verification_status=VERIFICATION_REQUIRED",
        "?processing_status=COMPLETED",
        "?ip_type=PATENT",
    ):
        r = client.get(f"/api/v1/admin/ip-records{params}", headers=_h(client, ADMIN))
        assert r.status_code == 200, r.text


def test_granted_as_verification_status_is_422_not_500(client):
    r = client.get("/api/v1/admin/ip-records?verification_status=GRANTED", headers=_h(client, ADMIN))
    assert r.status_code == 422, r.text
    assert r.json().get("error") == "VALIDATION_ERROR"
    assert "INTERNAL_ERROR" not in r.text


def test_unknown_processing_status_is_422_not_500(client):
    r = client.get("/api/v1/admin/ip-records?processing_status=NOPE", headers=_h(client, ADMIN))
    assert r.status_code == 422, r.text
    assert r.json().get("error") == "VALIDATION_ERROR"


def test_pagination_with_granted_filter(client):
    r = client.get("/api/v1/admin/ip-records?workflow_state=GRANTED&page=1&per_page=1", headers=_h(client, ADMIN))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["page"] == 1
    assert body["per_page"] == 1
    assert len(body["records"]) <= 1
    r2 = client.get("/api/v1/admin/ip-records?workflow_state=GRANTED&page=2&per_page=1", headers=_h(client, ADMIN))
    assert r2.status_code == 200, r2.text


def test_empty_granted_result(client):
    r = client.get(
        "/api/v1/admin/ip-records?workflow_state=GRANTED&search=zzz-no-such-record-zzz",
        headers=_h(client, ADMIN),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 0
    assert body["records"] == []
