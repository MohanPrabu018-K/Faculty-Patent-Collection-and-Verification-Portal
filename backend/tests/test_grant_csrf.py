"""Manual patent decisions were removed from the HOD and Admin surfaces.

This file previously proved the security wiring of `POST
/api/v1/admin/ip-records/{id}/grant`. That endpoint no longer exists, so the
tests now prove the stronger property: the grant decision is unreachable by any
role, through the UI API surface, including by direct API call.

The CSRF layer is still proven intact (it runs before routing), so a
missing-credential write is still rejected with CSRF_TOKEN_INVALID rather than
falling through to the router.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.config import app_settings
from app.core.security import generate_jwt_token
from app.main import app

GRANT_PATH = "/api/v1/admin/ip-records/76e50dba-6195-47b1-83a5-dde08b527854/grant"


@pytest.fixture(scope="module")
def bare_client():
    # Deliberately not used as a context manager: lifespan startup needs a live
    # database and none of the assertions below touch one.
    return TestClient(app)


def _tok(sub, role, dept="", fac=""):
    return generate_jwt_token(
        sub, app_settings.secret_key, app_settings.jwt_algorithm,
        minutes=30, email=f"{sub}@faculty.edu", role=role,
        faculty_id=fac or sub, department_id=dept, full_name=sub,
    )


ADMIN = {"Authorization": f"Bearer {_tok('test-admin-002', 'super_admin')}"}
HOD = {"Authorization": f"Bearer {_tok('test-hod-001', 'hod_admin', 'mv-dept', 'FAC-HOD')}"}
FAC1 = {"Authorization": f"Bearer {_tok('test-faculty-001', 'faculty', 'mv-dept', 'FAC001')}"}


def _authed(client, auth):
    client.cookies.set("csrf_token", "probe-token")
    headers = dict(auth)
    headers["X-CSRF-Token"] = "probe-token"
    return headers


def test_grant_route_is_not_registered(bare_client):
    """The grant route must not exist in the OpenAPI schema at all."""
    spec = bare_client.get("/openapi.json").json()
    assert GRANT_PATH not in spec["paths"]
    assert not any("grant" in p for p in spec["paths"]), spec["paths"].keys()


def test_grant_without_any_credentials_is_rejected(bare_client):
    """CSRF middleware still runs before routing: no pair -> 400."""
    r = bare_client.post(GRANT_PATH, json={})
    assert r.status_code == 400, r.text
    assert r.json().get("error") == "CSRF_TOKEN_INVALID"


def test_grant_with_csrf_pair_but_no_auth_is_not_found(bare_client):
    """A valid double-submit pair reaches routing, where the route is gone."""
    bare_client.cookies.set("csrf_token", "probe-token")
    r = bare_client.post(GRANT_PATH, json={}, headers={"X-CSRF-Token": "probe-token"})
    assert r.status_code == 404, r.text


def test_super_admin_cannot_grant_via_api(bare_client):
    """Even the highest role cannot grant: the route is removed, not just gated."""
    bare_client.cookies.set("csrf_token", "probe-token")
    r = bare_client.post(GRANT_PATH, json={}, headers=_authed(bare_client, ADMIN))
    assert r.status_code == 404, r.text


def test_hod_cannot_grant_via_api(bare_client):
    bare_client.cookies.set("csrf_token", "probe-token")
    r = bare_client.post(GRANT_PATH, json={}, headers=_authed(bare_client, HOD))
    assert r.status_code == 404, r.text


def test_faculty_cannot_grant_via_api(bare_client):
    bare_client.cookies.set("csrf_token", "probe-token")
    r = bare_client.post(GRANT_PATH, json={}, headers=_authed(bare_client, FAC1))
    assert r.status_code == 404, r.text


def test_grant_is_absent_for_every_http_method(bare_client):
    """No method (GET/PUT/PATCH/DELETE) resurrects a grant capability."""
    for method in ("GET", "PUT", "PATCH", "DELETE"):
        bare_client.cookies.set("csrf_token", "probe-token")
        r = bare_client.request(method, GRANT_PATH, headers=_authed(bare_client, ADMIN))
        assert r.status_code in (404, 405), (method, r.status_code, r.text)


def test_read_only_record_listing_survives(bare_client):
    """Removing the decision must not remove read-only admin record access.

    Unauthenticated this is a 401, which proves the route family still exists
    and is still authenticated (rather than having been stripped wholesale).
    """
    r = bare_client.get("/api/v1/admin/ip-records")
    assert r.status_code in (400, 401), r.text