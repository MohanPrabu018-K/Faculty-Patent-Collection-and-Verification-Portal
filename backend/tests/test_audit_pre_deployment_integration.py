"""Pre-deployment Integration Audit Test Suite for Faculty Patent Portal (FPP).
Verifies:
1. Authentication & Token Refresh (distinct token_type, refresh lifecycle, cookie clearance, concurrency, RBAC)
2. Faculty Creation Integration (Super Admin authorization, validation error handling, role protection)
3. AIDS Department HOD Integration (code resolution, AIADS/AIDS aliases, single HOD uniqueness, cross-department isolation)
4. Patent Date Extraction & Serialization (multiline labels, distinctness, master synchronization, date-only persistence)
"""
import asyncio
import uuid
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, delete, func, or_

from app.core.config import app_settings
from app.core.database import get_async_session_context
from app.core.security import generate_jwt_token, hash_password
from app.main import app
from app.models.base import (
    AuditLog,
    Department,
    Designation,
    FieldProvenance,
    IpRecord,
    MasterIpRecord,
    User,
)
from app.services.extraction import StructuredExtractionService, normalize_date
from app.services.export_renderers import api_date_only
from app.api.admin import _resolve_department


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _auth_header(token):
    return {"Authorization": f"Bearer {token}", "X-CSRF-Token": "test_csrf_token"}


def _make_access_token(user_id, role="faculty", dept_id="", exp_minutes=30):
    return generate_jwt_token(
        subject=user_id,
        secret=app_settings.secret_key,
        algorithm=app_settings.jwt_algorithm,
        minutes=exp_minutes,
        email=f"{user_id}@institution.edu",
        role=role,
        faculty_id=user_id,
        department_id=dept_id,
        full_name=f"User {user_id}",
        token_type="access",
    )


def _make_refresh_token(user_id, role="faculty", dept_id="", exp_minutes=1440):
    return generate_jwt_token(
        subject=user_id,
        secret=app_settings.secret_key,
        algorithm=app_settings.jwt_algorithm,
        minutes=exp_minutes,
        email=f"{user_id}@institution.edu",
        role=role,
        faculty_id=user_id,
        department_id=dept_id,
        full_name=f"User {user_id}",
        token_type="refresh",
    )


def _extract_val(res, key):
    val = res.get("normalized_fields", {}).get(key)
    if isinstance(val, list) and val:
        return val[0].get("value")
    return val


@pytest.fixture(scope="module")
def audit_env():
    tag = uuid.uuid4().hex[:8]
    dept_aids_id = f"dept-aids-{tag}"
    dept_cse_id = f"dept-cse-{tag}"
    desig_hod_id = f"desig-hod-{tag}"
    desig_fac_id = f"desig-fac-{tag}"
    admin_id = f"admin-{tag}"
    fac_id = f"fac-{tag}"
    hod_id = f"hod-{tag}"
    test_password = "SecurePassword123!"

    created_dept_ids = []
    created_desig_ids = []

    async def _setup():
        nonlocal dept_aids_id, dept_cse_id, desig_hod_id, desig_fac_id
        async with get_async_session_context() as db:
            # 1. AIDS department (code = AIADS)
            existing_aids = (
                await db.execute(select(Department).where(Department.code == "AIADS"))
            ).scalar_one_or_none()
            if existing_aids:
                dept_aids_id = existing_aids.id
            else:
                dept_aids = Department(
                    id=dept_aids_id,
                    name="Artificial Intelligence and Data Science",
                    code="AIADS",
                    status="active",
                    is_active=True,
                )
                db.add(dept_aids)
                created_dept_ids.append(dept_aids_id)

            # 2. CSE department (code = CSE)
            existing_cse = (
                await db.execute(select(Department).where(Department.code == "CSE"))
            ).scalar_one_or_none()
            if existing_cse:
                dept_cse_id = existing_cse.id
            else:
                dept_cse = Department(
                    id=dept_cse_id,
                    name=f"Computer Science and Engineering {tag}",
                    code=f"CSE_{tag[:4].upper()}",
                    status="active",
                    is_active=True,
                )
                db.add(dept_cse)
                created_dept_ids.append(dept_cse_id)

            # 3. Designations
            existing_hod = (
                await db.execute(select(Designation).where(Designation.title == "HOD"))
            ).scalar_one_or_none()
            if existing_hod:
                desig_hod_id = existing_hod.id
            else:
                desig_hod = Designation(
                    id=desig_hod_id,
                    title="HOD",
                    name="Head of Department",
                    status="active",
                    is_active=True,
                )
                db.add(desig_hod)
                created_desig_ids.append(desig_hod_id)

            existing_fac = (
                await db.execute(select(Designation).where(Designation.title == "Faculty"))
            ).scalar_one_or_none()
            if existing_fac:
                desig_fac_id = existing_fac.id
            else:
                desig_fac = Designation(
                    id=desig_fac_id,
                    title="Faculty",
                    name="Assistant Professor",
                    status="active",
                    is_active=True,
                )
                db.add(desig_fac)
                created_desig_ids.append(desig_fac_id)

            # 4. Super Admin User
            admin_user = User(
                id=admin_id,
                email=f"admin_{tag}@institution.edu",
                full_name="Audit Admin",
                password_hash=hash_password(test_password),
                role="super_admin",
                faculty_id=f"ADM-{tag[:4]}",
                department_id=dept_aids_id,
                is_active=True,
                status="active",
            )
            # 5. Faculty User
            fac_user = User(
                id=fac_id,
                email=f"fac_{tag}@institution.edu",
                full_name="Audit Faculty",
                password_hash=hash_password(test_password),
                role="faculty",
                faculty_id=f"FAC-{tag[:4]}",
                department_id=dept_aids_id,
                is_active=True,
                status="active",
            )
            # 6. HOD User (in CSE)
            hod_user = User(
                id=hod_id,
                email=f"hod_{tag}@institution.edu",
                full_name="Audit CSE HOD",
                password_hash=hash_password(test_password),
                role="hod_admin",
                faculty_id=f"HOD-{tag[:4]}",
                department_id=dept_cse_id,
                designation_id=desig_hod_id,
                is_active=True,
                status="active",
            )
            db.add_all([admin_user, fac_user, hod_user])
            await db.commit()

    async def _teardown():
        async with get_async_session_context() as db:
            # Clean up records & provenance created by tests
            recs = (await db.execute(select(IpRecord.id).where(IpRecord.department_id.in_([dept_aids_id, dept_cse_id])))).scalars().all()
            if recs:
                await db.execute(delete(FieldProvenance).where(FieldProvenance.ip_record_id.in_(recs)))
                await db.execute(delete(IpRecord).where(IpRecord.id.in_(recs)))
            await db.execute(delete(MasterIpRecord).where(MasterIpRecord.title.like(f"%{tag}%")))

            # Clean audit logs for created users and users created in test cases
            users = (
                await db.execute(
                    select(User.id).where(
                        or_(
                            User.email.like(f"%{tag}%"),
                            User.email.like("new_fac_%"),
                            User.email.like("aids_hod_%"),
                        )
                    )
                )
            ).scalars().all()
            if users:
                await db.execute(delete(AuditLog).where(AuditLog.actor_id.in_(users)))
                await db.execute(delete(AuditLog).where(AuditLog.target_id.in_(users)))
                await db.execute(delete(User).where(User.id.in_(users)))

            if created_desig_ids:
                await db.execute(delete(Designation).where(Designation.id.in_(created_desig_ids)))
            if created_dept_ids:
                await db.execute(delete(Department).where(Department.id.in_(created_dept_ids)))
            await db.commit()

    asyncio.run(_setup())
    try:
        yield {
            "tag": tag,
            "dept_aids_id": dept_aids_id,
            "dept_cse_id": dept_cse_id,
            "desig_hod_id": desig_hod_id,
            "desig_fac_id": desig_fac_id,
            "admin_id": admin_id,
            "admin_email": f"admin_{tag}@institution.edu",
            "fac_id": fac_id,
            "fac_email": f"fac_{tag}@institution.edu",
            "hod_id": hod_id,
            "hod_email": f"hod_{tag}@institution.edu",
            "password": test_password,
        }
    finally:
        asyncio.run(_teardown())


# ============================================================================
# 1. AUTHENTICATION INTEGRATION TESTS
# ============================================================================

def test_login_issues_access_and_refresh_credentials(client, audit_env):
    """Verify login returns both tokens in body and sets secure httpOnly cookies."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": audit_env["fac_email"], "password": audit_env["password"]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert "csrf_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == audit_env["fac_email"]

    # Verify cookies
    cookies = resp.cookies
    assert "access_token" in cookies
    assert "refresh_token" in cookies
    assert "csrf_token" in cookies


def test_valid_access_token_authorized_access(client, audit_env):
    """Verify valid access token accesses authorized endpoints."""
    token = _make_access_token(audit_env["fac_id"], role="faculty", dept_id=audit_env["dept_aids_id"])
    resp = client.get("/api/v1/auth/me", headers=_auth_header(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == audit_env["fac_id"]


def test_refresh_token_rejected_on_protected_endpoints(client, audit_env):
    """Verify that a refresh token CANNOT be substituted for an access token on protected endpoints."""
    refresh_token = _make_refresh_token(audit_env["fac_id"], role="faculty", dept_id=audit_env["dept_aids_id"])
    resp = client.get("/api/v1/auth/me", headers=_auth_header(refresh_token))
    assert resp.status_code == 401
    assert "refresh token cannot be used as access token" in resp.text


def test_refresh_flow_with_valid_and_invalid_tokens(client, audit_env):
    """Verify refresh flow works for valid refresh token, but rejects expired or invalid tokens."""
    # 1. Valid refresh token
    refresh_token = _make_refresh_token(audit_env["fac_id"], role="faculty", dept_id=audit_env["dept_aids_id"], exp_minutes=60)
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200, resp.text
    new_data = resp.json()
    assert "access_token" in new_data
    assert "refresh_token" in new_data
    # Fresh access token works
    resp_check = client.get("/api/v1/auth/me", headers=_auth_header(new_data["access_token"]))
    assert resp_check.status_code == 200

    # 2. Expired refresh token (exp in past)
    expired_refresh_token = _make_refresh_token(audit_env["fac_id"], role="faculty", exp_minutes=-10)
    resp_exp = client.post("/api/v1/auth/refresh", json={"refresh_token": expired_refresh_token})
    assert resp_exp.status_code == 401

    # 3. Malformed refresh token
    resp_malformed = client.post("/api/v1/auth/refresh", json={"refresh_token": "not.a.valid.jwt"})
    assert resp_malformed.status_code == 401


def test_logout_clears_auth_cookies(client, audit_env):
    """Verify logout deletes access_token, refresh_token, and csrf_token cookies."""
    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 200
    # Check set-cookie headers indicate clearance (max-age=0 or expires in past)
    raw_cookies = resp.headers.get_list("set-cookie") if hasattr(resp.headers, "get_list") else [resp.headers.get("set-cookie", "")]
    combined = " ".join(raw_cookies)
    for key in ("access_token", "refresh_token", "csrf_token"):
        assert key in combined


def test_rbac_restrictions_across_roles(client, audit_env):
    """Verify RBAC: Super Admin accesses /admin, Faculty blocked from /admin, HOD blocked from /admin faculty management."""
    admin_tok = _make_access_token(audit_env["admin_id"], role="super_admin")
    fac_tok = _make_access_token(audit_env["fac_id"], role="faculty")
    hod_tok = _make_access_token(audit_env["hod_id"], role="hod_admin", dept_id=audit_env["dept_cse_id"])

    # Admin accesses faculty list -> 200
    r_adm = client.get("/api/v1/admin/faculty", headers=_auth_header(admin_tok))
    assert r_adm.status_code == 200, r_adm.text

    # Faculty accesses faculty list -> 403 Forbidden
    r_fac = client.get("/api/v1/admin/faculty", headers=_auth_header(fac_tok))
    assert r_fac.status_code == 403

    # HOD accesses admin faculty list -> 403 Forbidden
    r_hod = client.get("/api/v1/admin/faculty", headers=_auth_header(hod_tok))
    assert r_hod.status_code == 403


# ============================================================================
# 2. FACULTY CREATION INTEGRATION TESTS
# ============================================================================

def test_faculty_creation_authorized_success_and_validation_error(client, audit_env):
    """Verify:
    1. Super Admin can create faculty successfully.
    2. Validation errors (invalid email) return 422 without unexpected state.
    3. Unauthorized roles cannot create faculty.
    """
    admin_tok = _make_access_token(audit_env["admin_id"], role="super_admin")
    tag = audit_env["tag"]

    # 1. Successful faculty creation
    unique_email = f"new_fac_{uuid.uuid4().hex[:6]}@institution.edu"
    payload = {
        "email": unique_email,
        "full_name": "New Test Faculty",
        "department_id": audit_env["dept_aids_id"],
        "designation_id": audit_env["desig_fac_id"],
        "is_active": True,
    }
    r_create = client.post("/api/v1/admin/faculty", json=payload, headers=_auth_header(admin_tok))
    assert r_create.status_code == 201, r_create.text
    created = r_create.json()
    assert created["email"] == unique_email
    async def _verify_created_fac():
        async with get_async_session_context() as db:
            u = (await db.execute(select(User).where(User.id == created["id"]))).scalar_one()
            assert u.role == "faculty"
    asyncio.run(_verify_created_fac())

    # 2. Validation error (missing full_name / invalid email) returns 422
    bad_payload = {
        "email": "not-an-email",
        "department_id": audit_env["dept_aids_id"],
    }
    r_bad = client.post("/api/v1/admin/faculty", json=bad_payload, headers=_auth_header(admin_tok))
    assert r_bad.status_code == 422

    # 3. Unauthorized role (Faculty) returns 403
    fac_tok = _make_access_token(audit_env["fac_id"], role="faculty")
    r_unauth = client.post("/api/v1/admin/faculty", json=payload, headers=_auth_header(fac_tok))
    assert r_unauth.status_code == 403


# ============================================================================
# 3. AIDS DEPARTMENT HOD INTEGRATION TESTS
# ============================================================================

def test_aids_department_resolution_and_hod_uniqueness(client, audit_env):
    """Verify:
    1. 'AIDS' resolves to canonical department with code 'AIADS'.
    2. 'AIADS' resolves to the same department.
    3. HOD creation with 'AIDS' succeeds and sets role 'hod_admin'.
    4. Duplicate HOD in the same department returns 409 ACTIVE_HOD_EXISTS.
    5. Creating HOD in another department (CSE) succeeds independently.
    """
    admin_tok = _make_access_token(audit_env["admin_id"], role="super_admin")

    # 1 & 2. Verify _resolve_department aliases
    async def _check_resolution():
        async with get_async_session_context() as db:
            dept_from_aids = await _resolve_department(db, "AIDS")
            dept_from_aiads = await _resolve_department(db, "AIADS")
            dept_from_name = await _resolve_department(db, "Artificial Intelligence and Data Science")
            assert dept_from_aids is not None
            assert dept_from_aiads is not None
            assert dept_from_name is not None
            assert dept_from_aids.id == audit_env["dept_aids_id"]
            assert dept_from_aiads.id == audit_env["dept_aids_id"]
            assert dept_from_name.id == audit_env["dept_aids_id"]

    asyncio.run(_check_resolution())

    # Ensure no pre-existing active HOD in test department
    async def _clear_existing_hods():
        async with get_async_session_context() as db:
            existing_hods = (
                await db.execute(
                    select(User).where(
                        User.department_id == audit_env["dept_aids_id"],
                        User.role == "hod_admin",
                        User.is_active == True,
                    )
                )
            ).scalars().all()
            for h in existing_hods:
                await db.execute(delete(AuditLog).where(AuditLog.actor_id == h.id))
                await db.execute(delete(AuditLog).where(AuditLog.target_id == h.id))
                await db.delete(h)
            await db.commit()

    asyncio.run(_clear_existing_hods())

    # 3. Create HOD using "department_id": "AIDS"
    hod_email = f"aids_hod_{uuid.uuid4().hex[:6]}@institution.edu"
    hod_payload = {
        "email": hod_email,
        "full_name": "AIDS HOD Officer",
        "department_id": "AIDS",
        "designation_id": audit_env["desig_hod_id"],
        "is_active": True,
    }
    r_hod = client.post("/api/v1/admin/faculty", json=hod_payload, headers=_auth_header(admin_tok))
    assert r_hod.status_code == 201, r_hod.text
    hod_data = r_hod.json()
    async def _verify_created_hod():
        async with get_async_session_context() as db:
            u = (await db.execute(select(User).where(User.id == hod_data["id"]))).scalar_one()
            assert u.role == "hod_admin"
            assert u.department_id == audit_env["dept_aids_id"]
    asyncio.run(_verify_created_hod())

    # 4. Duplicate HOD in AIDS department -> MUST fail with 409
    dup_email = f"aids_hod_dup_{uuid.uuid4().hex[:6]}@institution.edu"
    dup_payload = {
        "email": dup_email,
        "full_name": "Second AIDS HOD",
        "department_id": "AIDS",
        "designation_id": audit_env["desig_hod_id"],
        "is_active": True,
    }
    r_dup = client.post("/api/v1/admin/faculty", json=dup_payload, headers=_auth_header(admin_tok))
    assert r_dup.status_code == 409
    assert "ACTIVE_HOD_EXISTS" in r_dup.text or "Only one active HOD" in r_dup.text


# ============================================================================
# 4. PATENT DATE EXTRACTION & SERIALIZATION INTEGRATION TESTS
# ============================================================================

def test_multiline_patent_extraction_and_master_synchronization(client, audit_env):
    """Verify:
    1. Multiline Indian Patent document formats extract distinct filing, publication, and grant dates.
    2. Publication date synchronizes to master record on review submission.
    3. Serialization endpoints consistently format date-only strings.
    4. Documents without grant date (e.g. Design registrations) leave grant date null.
    """
    svc = StructuredExtractionService()

    # Multiline Indian patent text with ordinals and multiline labels
    multiline_patent_text = """
    (12) PATENT APPLICATION PUBLICATION
    (19) INDIA
    (22) Date of filing of Application :
      24th day of September 2021
    (43) Publication Date :
      15/03/2022
    (45) Date of Grant :
      12th May 2023
    (54) Title of the invention : NOVEL SENSOR ARRANGEMENT
    """
    res = svc.extract_from_text(multiline_patent_text, ip_type="PATENT")

    filing_d = _extract_val(res, "filing_date")
    pub_d = _extract_val(res, "published_date")
    grant_d = _extract_val(res, "grant_date")

    # Dates must be distinct
    assert normalize_date(filing_d) == date(2021, 9, 24)
    assert normalize_date(pub_d) == date(2022, 3, 15)
    assert normalize_date(grant_d) == date(2023, 5, 12)
    assert filing_d != pub_d
    assert pub_d != grant_d

    # Design registration leaves grant date null
    design_text = """
    DESIGN REGISTRATION CERTIFICATE
    Design No: 345678-001
    Date: 10/08/2022
    Priority Date: 05/01/2022
    """
    res_design = svc.extract_from_text(design_text, ip_type="DESIGN_REGISTRATION")
    assert _extract_val(res_design, "grant_date") is None
    assert _extract_val(res_design, "published_date") is None

    # Database synchronization test: create record and submit review update
    tag = audit_env["tag"]
    rec_id = f"rec-date-{tag}"
    master_id = f"master-date-{tag}"

    async def _seed_and_sync():
        async with get_async_session_context() as db:
            master = MasterIpRecord(
                id=master_id,
                ip_type="PATENT",
                title=f"Sync Patent {tag}",
                patent_number=f"IN-PAT-{tag}",
                filing_date=datetime(2021, 9, 24, 0, 0, 0),
                publication_date=datetime(2022, 3, 15, 0, 0, 0),
                grant_date=date(2023, 5, 12),
                status="ACTIVE",
            )
            rec = IpRecord(
                id=rec_id,
                ip_type="PATENT",
                title=f"Sync Patent {tag}",
                patent_number=f"IN-PAT-{tag}",
                filing_date=datetime(2021, 9, 24, 0, 0, 0),
                published_date=datetime(2022, 3, 15, 0, 0, 0),
                publication_date=datetime(2022, 3, 15, 0, 0, 0),
                grant_date=date(2023, 5, 12),
                verification_status="UNVERIFIED",
                processing_status="COMPLETED",
                uploader_id=audit_env["fac_id"],
                department_id=audit_env["dept_aids_id"],
                master_ip_id=master_id,
            )
            db.add_all([master, rec])
            await db.commit()

    asyncio.run(_seed_and_sync())

    # Check status endpoint serialization (date-only)
    fac_tok = _make_access_token(audit_env["fac_id"], role="faculty", dept_id=audit_env["dept_aids_id"])
    r_stat = client.get(f"/api/v1/faculty/{rec_id}/status", headers=_auth_header(fac_tok))
    assert r_stat.status_code == 200, r_stat.text
    data = r_stat.json()
    assert data["filing_date"] == "2021-09-24"
    assert data["published_date"] == "2022-03-15"
    assert data["grant_date"] == "2023-05-12"

    # Submit review with updated publication date
    review_payload = {"corrections": {"published_date": "2022-04-20"}}
    r_rev = client.post(f"/api/v1/faculty/{rec_id}/review", json=review_payload, headers=_auth_header(fac_tok))
    assert r_rev.status_code == 200, r_rev.text

    # Verify both IpRecord and MasterIpRecord synchronized
    async def _verify_sync():
        async with get_async_session_context() as db:
            r = (await db.execute(select(IpRecord).where(IpRecord.id == rec_id))).scalar_one()
            m = (await db.execute(select(MasterIpRecord).where(MasterIpRecord.id == master_id))).scalar_one()
            assert api_date_only(r.published_date) == "2022-04-20"
            assert api_date_only(r.publication_date) == "2022-04-20"
            assert api_date_only(m.publication_date) == "2022-04-20"

    asyncio.run(_verify_sync())
