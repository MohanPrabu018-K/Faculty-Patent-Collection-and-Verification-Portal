"""Regression test suite for the 4 production audit issues:
1. Patent date extraction (filing, publication, grant distinctness, multiline labels, ordinal dates, design null dates, master sync)
2. Faculty creation navigation & error handling
3. AIDS department identifier resolver & HOD uniqueness / department isolation
4. Authentication token refresh lifecycle & protection
"""
import asyncio
import uuid
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, delete

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


def _h(token):
    return {"Authorization": f"Bearer {token}", "X-CSRF-Token": "test_token"}


def _tok(sub, role="super_admin", dept="", fac=""):
    return generate_jwt_token(
        subject=sub,
        secret=app_settings.secret_key,
        algorithm=app_settings.jwt_algorithm,
        minutes=30,
        email=f"{sub}@institution.edu",
        role=role,
        faculty_id=fac or sub,
        department_id=dept,
        full_name=sub,
        token_type="access",
    )


def _refresh_tok(sub, role="faculty", dept="", fac=""):
    return generate_jwt_token(
        subject=sub,
        secret=app_settings.secret_key,
        algorithm=app_settings.jwt_algorithm,
        minutes=app_settings.jwt_refresh_token_days * 24 * 60,
        email=f"{sub}@institution.edu",
        role=role,
        faculty_id=fac or sub,
        department_id=dept,
        full_name=sub,
        token_type="refresh",
    )


def _extract_val(res, key):
    val = res.get("normalized_fields", {}).get(key)
    if isinstance(val, list) and val:
        return val[0].get("value")
    return val


# ============================================================================
# ISSUE 1: PATENT DATE EXTRACTION REGRESSION TESTS
# ============================================================================

def test_normalize_date_formats_and_ordinals():
    """Verify normalize_date handles ordinal dates, days of week, and Indian patent formats."""
    # Ordinal dates
    assert normalize_date("12th May 2021") == date(2021, 5, 12)
    assert normalize_date("1st January 2022") == date(2022, 1, 1)
    assert normalize_date("22nd October 2024") == date(2024, 10, 22)
    assert normalize_date("23rd March 2020") == date(2020, 3, 23)
    assert normalize_date("24th day of September 2021") == date(2021, 9, 24)

    # Standard Indian slash / dash / dot formats
    assert normalize_date("15/03/2021") == date(2021, 3, 15)
    assert normalize_date("15-03-2021") == date(2021, 3, 15)
    assert normalize_date("15.03.2021") == date(2021, 3, 15)
    assert normalize_date("2021-03-15") == date(2021, 3, 15)


def test_patent_date_extraction_multiline_and_distinctness():
    """Verify extraction of filing, publication, and grant dates handles multiline headings
    and keeps them strictly distinct.
    """
    svc = StructuredExtractionService()

    # Multiline Indian Patent Journal sample text
    journal_ocr = """
    THE PATENT OFFICE JOURNAL
    (12) PATENT APPLICATION PUBLICATION
    (19) INDIA
    (22) Date of filing of Application :
    15/03/2021
    (21) Application No.202141010890 A
    (43) Date of publication of application :
    24/09/2021
    (54) Title of the invention : IOT BASED SMART AGRICULTURAL MONITORING SYSTEM
    (71) Name of Applicant :
    1)R P SARATHY INSTITUTE OF TECHNOLOGY
    (72) Name of Inventor :
    1)Dr. A. Sharma
    """

    res = svc.extract_from_text(journal_ocr, ip_type="PATENT")

    # Filing date extracted from multiline
    assert _extract_val(res, "filing_date") == date(2021, 3, 15)
    # Publication date extracted from multiline
    assert _extract_val(res, "published_date") == date(2021, 9, 24)
    # In a publication journal, grant date MUST BE NULL (not conflated)
    assert _extract_val(res, "grant_date") is None


def test_patent_certificate_grant_date_distinct():
    """Verify grant date on a patent certificate does not overwrite filing or publication date."""
    svc = StructuredExtractionService()

    certificate_ocr = """
    PATENT CERTIFICATE
    Patent No. : 501234
    Application No. : 202041005678
    Date of Filing : 10/02/2020
    Date of Grant of Patent : 18th March 2024
    Title : ADVANCED THERMAL SENSOR APPARATUS
    """

    res = svc.extract_from_text(certificate_ocr, ip_type="PATENT")

    assert _extract_val(res, "filing_date") == date(2020, 2, 10)
    assert _extract_val(res, "grant_date") == date(2024, 3, 18)
    # Publication date was not present, must remain null
    assert _extract_val(res, "published_date") is None


def test_design_registration_leaves_grant_and_published_dates_null():
    """Verify that design registrations leave grant_date and published_date null."""
    svc = StructuredExtractionService()

    design_ocr = """
    CERTIFICATE OF REGISTRATION OF DESIGN
    Design No. : 412345-001
    Date : 14/06/2023
    Priority : None
    Class : 14-03
    Title : SMART SENSOR HOUSING
    """

    res = svc.extract_from_text(design_ocr, ip_type="DESIGN_REGISTRATION")

    assert _extract_val(res, "design_number") == "412345-001"
    assert _extract_val(res, "registration_date") == date(2023, 6, 14)
    assert _extract_val(res, "grant_date") is None
    assert _extract_val(res, "published_date") is None


TAG = uuid.uuid4().hex[:8]


@pytest.fixture(scope="module")
def test_world():
    admin_id = f"t-adm-{TAG}"
    fac_id = f"t-fac-{TAG}"
    rec_id = f"t-rec-{TAG}"
    master_id = f"t-mst-{TAG}"
    dept_id = f"t-dept-{TAG}"
    aids_dept_id = f"t-aids-{TAG}"
    desig_id = f"t-desig-{TAG}"

    async def _setup():
        nonlocal aids_dept_id, desig_id
        async with get_async_session_context() as db:
            # Create probe department
            dept = Department(
                id=dept_id,
                name=f"Dept Probe {TAG}",
                code=f"DP{TAG[:4].upper()}",
                status="active",
                is_active=True,
            )
            # Create AIDS department if not existing
            existing_aids = (
                await db.execute(select(Department).where(Department.code == "AIADS"))
            ).scalar_one_or_none()
            if not existing_aids:
                aids_dept = Department(
                    id=aids_dept_id,
                    name="Artificial Intelligence and Data Science",
                    code="AIADS",
                    status="active",
                    is_active=True,
                )
                db.add(aids_dept)
            else:
                aids_dept_id = existing_aids.id

            # Ensure HOD designation exists
            existing_desig = (
                await db.execute(select(Designation).where(Designation.title == "HOD"))
            ).scalar_one_or_none()
            if not existing_desig:
                desig = Designation(
                    id=desig_id,
                    title="HOD",
                    name="Head of Department",
                    status="active",
                    is_active=True,
                )
                db.add(desig)
            else:
                desig_id = existing_desig.id

            db.add(dept)

            # Create Super Admin and Faculty User
            admin_user = User(
                id=admin_id,
                email=f"{admin_id}@institution.edu",
                full_name="Audit Super Admin",
                password_hash=hash_password("AdminPass123!"),
                role="super_admin",
                faculty_id=f"ADM-{TAG[:4]}",
                department_id=dept_id,
                is_active=True,
                status="active",
            )
            fac_user = User(
                id=fac_id,
                email=f"{fac_id}@institution.edu",
                full_name="Audit Faculty",
                password_hash=hash_password("FacPass123!"),
                role="faculty",
                faculty_id=f"FAC-{TAG[:4]}",
                department_id=dept_id,
                is_active=True,
                status="active",
            )
            db.add_all([admin_user, fac_user])

            # Create Master and IpRecord with published_date
            master = MasterIpRecord(
                id=master_id,
                ip_type="PATENT",
                patent_number=f"PAT-{TAG}",
                application_number=f"APP-{TAG}",
                title="Master Probe Title",
                filing_date=datetime(2022, 1, 10, 12, 0, 0),
                publication_date=datetime(2022, 6, 15, 12, 0, 0),
                grant_date=date(2024, 5, 20),
                status="ACTIVE",
            )
            rec = IpRecord(
                id=rec_id,
                ip_type="PATENT",
                patent_number=f"PAT-{TAG}",
                application_number=f"APP-{TAG}",
                title="Master Probe Title",
                filing_date=datetime(2022, 1, 10, 12, 0, 0),
                published_date=datetime(2022, 6, 15, 12, 0, 0),
                publication_date=datetime(2022, 6, 15, 12, 0, 0),
                grant_date=date(2024, 5, 20),
                verification_status="VERIFIED",
                processing_status="COMPLETED",
                workflow_state="VERIFIED",
                uploader_id=fac_id,
                department_id=dept_id,
                master_ip_id=master_id,
            )
            db.add_all([master, rec])
            await db.commit()

    async def _teardown():
        async with get_async_session_context() as db:
            await db.execute(delete(FieldProvenance).where(FieldProvenance.ip_record_id == rec_id))
            await db.execute(delete(IpRecord).where(IpRecord.id == rec_id))
            await db.execute(delete(MasterIpRecord).where(MasterIpRecord.id == master_id))
            await db.execute(delete(AuditLog).where(AuditLog.actor_id.in_([admin_id, fac_id])))
            await db.execute(delete(AuditLog).where(AuditLog.target_id.in_([admin_id, fac_id])))
            await db.execute(delete(User).where(User.id.in_([admin_id, fac_id])))
            await db.execute(delete(Department).where(Department.id == dept_id))
            await db.commit()

    asyncio.run(_setup())
    try:
        yield {
            "admin_id": admin_id,
            "fac_id": fac_id,
            "rec_id": rec_id,
            "master_id": master_id,
            "dept_id": dept_id,
            "aids_dept_id": aids_dept_id,
            "desig_id": desig_id,
        }
    finally:
        asyncio.run(_teardown())


def test_consistent_date_only_api_serialization(client, test_world):
    """Verify that filing_date, published_date, and grant_date are serialized consistently
    as date-only 'YYYY-MM-DD' without ISO timestamp leaks.
    """
    token = _tok(test_world["fac_id"], role="faculty", dept=test_world["dept_id"])
    headers = _h(token)

    r = client.get(f"/api/v1/faculty/{test_world['rec_id']}/status", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["filing_date"] == "2022-01-10"
    assert data["published_date"] == "2022-06-15"
    assert data["grant_date"] == "2024-05-20"


def test_publication_date_synchronization_to_master(client, test_world):
    """Verify that updating published_date on a faculty review synchronizes
    both IpRecord.publication_date and MasterIpRecord.publication_date.
    """
    token = _tok(test_world["fac_id"], role="faculty", dept=test_world["dept_id"])
    headers = _h(token)

    payload = {"corrections": {"published_date": "2022-08-30"}}
    r = client.post(f"/api/v1/faculty/{test_world['rec_id']}/review", json=payload, headers=headers)
    assert r.status_code == 200, r.text

    async def _check_db():
        async with get_async_session_context() as db:
            rec = (await db.execute(select(IpRecord).where(IpRecord.id == test_world["rec_id"]))).scalar_one()
            master = (await db.execute(select(MasterIpRecord).where(MasterIpRecord.id == test_world["master_id"]))).scalar_one()
            assert api_date_only(rec.published_date) == "2022-08-30"
            assert api_date_only(rec.publication_date) == "2022-08-30"
            assert api_date_only(master.publication_date) == "2022-08-30"

    asyncio.run(_check_db())


# ============================================================================
# ISSUE 3: AIDS DEPARTMENT IDENTIFIER RESOLVER & HOD CREATION
# ============================================================================

def test_resolve_department_supports_aids_aiads_uuid_and_name(test_world):
    """Verify _resolve_department resolves UUID, code 'AIADS', alias 'AIDS', and full name."""
    async def _test():
        async with get_async_session_context() as db:
            aiads_dept = (
                await db.execute(select(Department).where(Department.id == test_world["aids_dept_id"]))
            ).scalar_one()

            # 1. Resolve by canonical UUID
            res1 = await _resolve_department(db, aiads_dept.id)
            assert res1 is not None and res1.id == aiads_dept.id

            # 2. Resolve by database code 'AIADS'
            res2 = await _resolve_department(db, "AIADS")
            assert res2 is not None and res2.id == aiads_dept.id

            # 3. Resolve by alias 'AIDS'
            res3 = await _resolve_department(db, "AIDS")
            assert res3 is not None and res3.id == aiads_dept.id

            # 4. Resolve by lowercase 'aids'
            res4 = await _resolve_department(db, "aids")
            assert res4 is not None and res4.id == aiads_dept.id

            # 5. Resolve by full department name
            res5 = await _resolve_department(db, "Artificial Intelligence and Data Science")
            assert res5 is not None and res5.id == aiads_dept.id

    asyncio.run(_test())


def test_admin_create_hod_with_aids_code_resolves_and_enforces_uniqueness(client, test_world):
    """Verify that POST /admin/faculty with 'department_id': 'AIDS' creates HOD with canonical UUID,
    and a second HOD creation for the same department is rejected with 409 ACTIVE_HOD_EXISTS.
    """
    admin_token = _tok(test_world["admin_id"], role="super_admin")
    headers = _h(admin_token)

    unique_email = f"hod_aids_{uuid.uuid4().hex[:6]}@institution.edu"
    created_hod_id = None

    try:
        # Create HOD using "department_id": "AIDS"
        create_payload = {
            "email": unique_email,
            "full_name": "AIDS HOD Probe",
            "department_id": "AIDS",
            "designation_id": test_world["desig_id"],
            "is_active": True,
        }
        res = client.post("/api/v1/admin/faculty", json=create_payload, headers=headers)
        assert res.status_code == 201, res.text
        data = res.json()
        created_hod_id = data["id"]

        # Confirm the created user in DB has canonical department UUID
        async def _check_user():
            async with get_async_session_context() as db:
                user = (await db.execute(select(User).where(User.id == created_hod_id))).scalar_one()
                dept = (await db.execute(select(Department).where(Department.id == user.department_id))).scalar_one()
                assert dept.code == "AIADS"
                assert user.role == "hod_admin"

        asyncio.run(_check_user())

        # Attempt to create SECOND active HOD in same department -> must fail with 409
        dup_payload = {
            "email": f"hod_aids_dup_{uuid.uuid4().hex[:6]}@institution.edu",
            "full_name": "Second AIDS HOD",
            "department_id": "AIDS",
            "designation_id": test_world["desig_id"],
            "is_active": True,
        }
        res2 = client.post("/api/v1/admin/faculty", json=dup_payload, headers=headers)
        assert res2.status_code == 409, res2.text
        assert "ACTIVE_HOD_EXISTS" in res2.text or "Only one active HOD" in res2.text

    finally:
        if created_hod_id:
            async def _cleanup():
                async with get_async_session_context() as db:
                    await db.execute(delete(AuditLog).where(AuditLog.target_id == created_hod_id))
                    u = (await db.execute(select(User).where(User.id == created_hod_id))).scalar_one_or_none()
                    if u:
                        await db.delete(u)
                        await db.commit()
            asyncio.run(_cleanup())


# ============================================================================
# ISSUE 4 & 2: AUTHENTICATION TOKEN REFRESH & NAVIGATION BEHAVIOR
# ============================================================================

def test_refresh_token_lifecycle_and_rejection_on_protected_endpoints(client, test_world):
    """Verify that:
    1. A refresh token cannot be used directly as an access token on protected endpoints.
    2. POST /auth/refresh returns a fresh access token.
    3. Missing or invalid refresh tokens return 401 cleanly.
    """
    # 1. Attempt to access protected endpoint using refresh token as Bearer -> MUST fail 401
    refresh_token = _refresh_tok(test_world["fac_id"], role="faculty", dept=test_world["dept_id"])
    headers_with_refresh = _h(refresh_token)

    r_protected = client.get("/api/v1/faculty/dashboard", headers=headers_with_refresh)
    assert r_protected.status_code == 401
    assert "refresh token cannot be used as access token" in r_protected.text

    # 2. Call /auth/refresh with refresh token in JSON body
    r_refresh = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert r_refresh.status_code == 200, r_refresh.text
    refresh_data = r_refresh.json()
    assert "access_token" in refresh_data
    assert "refresh_token" in refresh_data
    new_access_token = refresh_data["access_token"]

    # 3. New access token works on protected endpoint
    headers_valid = _h(new_access_token)
    r_ok = client.get("/api/v1/faculty/dashboard", headers=headers_valid)
    assert r_ok.status_code == 200, r_ok.text

    # 4. Malformed refresh token fails cleanly with 401
    r_bad = client.post("/api/v1/auth/refresh", json={"refresh_token": "malformed.invalid.token"})
    assert r_bad.status_code == 401
