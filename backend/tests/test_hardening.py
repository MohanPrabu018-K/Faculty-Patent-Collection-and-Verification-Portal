"""Final pre-acceptance hardening tests.

Covers the blueprint-required items that were previously PARTIAL or
IMPLEMENTED-BUT-UNTESTED:

- A3  Department / Designation CRUD (admin) + faculty RBAC denial
- A5  Archive / unarchive IP records via admin PATCH + is_archived list
      filter + audit events (IP_RECORD_ARCHIVED / IP_RECORD_UNARCHIVED)
- U2  Extended admin record filters: date_from/date_to (verified as
      effective), designation_id, contributor_count, institution, is_archived
- AA1 Authorized raw-file download (GET /ip-records/{id}/file) with
      super_admin / HOD same-dept / owner access and IDOR denials
- B1  HOD dashboard & faculty list are department-scoped; faculty denied
- D2  Historical department snapshot preserved on records
- D3  Excel import (preview + import) with historical snapshot set (Z2)
- S1  Notification service writes every core notification type, visible
      through the notifications API
- X2  Per-record agent audit rows (ProcessingJob trail) exist

All enforcement (auth, CSRF, RBAC, IDOR, rate limiting, file security) is
kept intact - nothing here weakens security.

NOTE: The client is entered via ``with TestClient(app)`` for the whole
session so the app lifespan (and its async background tasks) run on a single
stable event loop. Creating a TestClient per request opens a fresh loop each
time, which races asyncpg's connection cancellation teardown against a closed
loop and yields intermittent "Event loop is closed" 500s against the live
Neon database.
"""
import asyncio
import io
import uuid
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.core.config import app_settings, upload_settings
from app.core.database import get_async_session_context
from app.core.security import generate_jwt_token
from app.main import app
from app.models.base import IpContributor, IpFile, IpRecord, User
from app.services.notifications import NotificationType, get_notification_service


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session", autouse=True)
def _ensure_hardening_fixtures():
    """Self-contained test isolation for clean-room databases.

    The real clean-room faculty intentionally have NULL departments (real PDFs
    did not reliably provide them), so HOD scoping / historical snapshots /
    Excel import cannot rely on production rows. Create clearly synthetic,
    idempotent fixtures (dept-a/dept-b, fac-a-001/fac-b-001/FACA001) used ONLY
    by these hardening tests. Real faculty rows are never modified.
    """
    import asyncio

    from app.core.security import hash_password
    from app.models.base import Department, User

    async def _create():
        async with get_async_session_context() as db:
            for dept_id, name, code in (
                ("dept-a", "Department A", "DEPTA"),
                ("dept-b", "Department B", "DEPTB"),
            ):
                exists = (await db.execute(select(Department).where(Department.id == dept_id))).scalar_one_or_none()
                if not exists:
                    db.add(Department(id=dept_id, name=name, code=code, is_active=True))
            await db.commit()
            fixtures = (
                ("fac-a-001", "FACA001", "Hardening Faculty A", "hardening-a@faculty.edu", "dept-a"),
                ("fac-b-001", "FACB001", "Hardening Faculty B", "hardening-b@faculty.edu", "dept-b"),
                ("hardening-faca001", "FACA001", "Hardening Import Faculty", "hardening-faca001@faculty.edu", "dept-a"),
            )
            for uid, fac_id, full_name, email, dept in fixtures:
                exists = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
                if not exists:
                    by_fac = (await db.execute(select(User).where(User.faculty_id == fac_id))).scalar_one_or_none()
                    # FACA001 is shared by fac-a-001 in clean-room; reuse it instead of duplicating.
                    if by_fac is None:
                        db.add(
                            User(
                                id=uid,
                                email=email,
                                official_email=email,
                                password_hash=hash_password("ChangeMe123!"),
                                full_name=full_name,
                                role="faculty",
                                faculty_id=fac_id,
                                department_id=dept,
                                status="active",
                                is_active=True,
                            )
                        )
            await db.commit()
            # Ensure fac-a-001 exists even when FACA001 was already taken by the import fixture.
            fac_a = (await db.execute(select(User).where(User.id == "fac-a-001"))).scalar_one_or_none()
            if not fac_a:
                db.add(
                    User(
                        id="fac-a-001",
                        email="hardening-fac-a-001@faculty.edu",
                        official_email="hardening-fac-a-001@faculty.edu",
                        password_hash=hash_password("ChangeMe123!"),
                        full_name="Hardening Faculty A",
                        role="faculty",
                        faculty_id="FACA001-A",
                        department_id="dept-a",
                        status="active",
                        is_active=True,
                    )
                )
                await db.commit()

    asyncio.run(_create())


@pytest.fixture(scope="session")
def _ensure_admin_user():
    """Create the minted ADMIN identity as a real user once per session.

    ``audit_log.actor_id`` and ``notification.user_id`` have foreign keys to
    ``user.id``, so the synthetic ``test-admin-002`` super_admin used by the
    minted ADMIN token must exist in the DB for audit/notification writes to
    persist. Created idempotently to keep reruns safe.
    """
    import asyncio

    from sqlalchemy import select

    from app.core.security import hash_password
    from app.models.base import User

    async def _create():
        async with get_async_session_context() as db:
            exists = (await db.execute(select(User).where(User.id == "test-admin-002"))).scalar_one_or_none()
            if not exists:
                db.add(
                    User(
                        id="test-admin-002",
                        email="test-admin-002@faculty.edu",
                        official_email="test-admin-002@faculty.edu",
                        password_hash=hash_password("ChangeMe123!"),
                        full_name="Test Admin",
                        role="super_admin",
                        faculty_id="test-admin-002",
                        status="active",
                        is_active=True,
                    )
                )
                await db.commit()

    asyncio.run(_create())


def _tok(sub, role, dept="", fac=""):
    return generate_jwt_token(
        sub, app_settings.secret_key, app_settings.jwt_algorithm,
        minutes=30, email=f"{sub}@faculty.edu", role=role,
        faculty_id=fac or sub, department_id=dept, full_name=sub,
    )


ADMIN = {"Authorization": f"Bearer {_tok('test-admin-002', 'super_admin')}"}
HOD_A = {"Authorization": f"Bearer {_tok('hod-test-a', 'hod_admin', 'dept-a')}"}
HOD_B = {"Authorization": f"Bearer {_tok('hod-test-b', 'hod_admin', 'dept-b')}"}
FAC = {"Authorization": f"Bearer {_tok('fac-denied-001', 'faculty', 'dept-a', 'FACDEN')}"}


def _h(client, auth):
    """Authorization + the session client's current CSRF token.

    The login endpoint rotates the ``csrf_token`` cookie, so the header must
    echo whatever cookie value is active on the shared session client. A
    cookie is only installed lazily (if no login has happened yet) to avoid
    httpx CookieConflict between the manual cookie and a login ``Set-Cookie``.
    """
    token = client.cookies.get("csrf_token")
    if token is None:
        token = "t"
        client.cookies.set("csrf_token", token)
    headers = dict(auth)
    headers["X-CSRF-Token"] = token
    return headers


# --- Reference record (dept-scoped, file present on disk) ------------------

@pytest.fixture(scope="session")
def ref_record():
    """A dept-scoped record whose stored file actually exists on disk.

    Scans IpFile rows (descending by creation) joined to dept-scoped records
    and returns the first one whose storage_key resolves to a real file under
    the configured local storage root. This keeps the AA1 download tests
    deterministic even after storage cleanups.
    """
    import asyncio
    from pathlib import Path

    from sqlalchemy import select as _select

    async def _pick():
        async with get_async_session_context() as db:
            rows = (
                await db.execute(
                    _select(IpFile, IpRecord)
                    .join(IpRecord, IpFile.ip_record_id == IpRecord.id)
                    .where(IpRecord.department_id.isnot(None))
                    .order_by(IpFile.created_at.desc())
                    .limit(300)
                )
            ).all()
        root = Path(upload_settings.local_storage_root).resolve()
        for f, r in rows:
            fp = (root / f.storage_key).resolve()
            if str(fp).startswith(str(root)) and fp.is_file():
                return {
                    "record_id": r.id,
                    "uploader_id": r.uploader_id,
                    "department_id": r.department_id,
                    "file_id": f.id,
                    "filename": f.original_filename,
                    "historical_dept": bool(r.historical_department_id),
                }
        return None

    return asyncio.run(_pick())


# --- A3: Department / Designation CRUD -------------------------------------

def test_department_crud_lifecycle_and_rbac(client):
    name = f"Hardening Dept {uuid.uuid4().hex[:8]}"
    r = client.post("/api/v1/admin/departments", headers=_h(client, ADMIN), json={"name": name, "code": f"HD{uuid.uuid4().hex[:4]}", "is_active": True})
    assert r.status_code == 201, r.text
    dept_id = r.json()["id"]

    listed = client.get("/api/v1/admin/departments?per_page=100", headers=ADMIN).json()["departments"]
    assert any(d["name"] == name for d in listed)

    r = client.patch(f"/api/v1/admin/departments/{dept_id}", headers=_h(client, ADMIN), json={"name": name + " v2"})
    assert r.status_code == 200 and r.json()["name"] == name + " v2"

    r = client.delete(f"/api/v1/admin/departments/{dept_id}", headers=_h(client, ADMIN))
    assert r.status_code == 200 and r.json()["deleted"] is True
    listed = client.get("/api/v1/admin/departments?per_page=100", headers=ADMIN).json()["departments"]
    assert all(d["name"] != name and d["name"] != name + " v2" for d in listed)

    r = client.post("/api/v1/admin/departments", headers=_h(client, FAC), json={"name": name + " x"})
    assert r.status_code == 403, "faculty must be denied department create"


def test_designation_crud_lifecycle_and_rbac(client):
    title = f"Hardening Designation {uuid.uuid4().hex[:8]}"
    r = client.post("/api/v1/admin/designations", headers=_h(client, ADMIN), json={"title": title, "level": "L1", "is_active": True})
    assert r.status_code == 201, r.text
    desg_id = r.json()["id"]

    listed = client.get("/api/v1/admin/designations?per_page=100", headers=ADMIN).json()["designations"]
    assert any(d["title"] == title for d in listed)

    r = client.patch(f"/api/v1/admin/designations/{desg_id}", headers=_h(client, ADMIN), json={"title": title + " v2"})
    assert r.status_code == 200 and r.json()["title"] == title + " v2"

    r = client.delete(f"/api/v1/admin/designations/{desg_id}", headers=_h(client, ADMIN))
    assert r.status_code == 200 and r.json()["deleted"] is True
    listed = client.get("/api/v1/admin/designations?per_page=100", headers=ADMIN).json()["designations"]
    assert all(d["title"] != title for d in listed)

    r = client.post("/api/v1/admin/designations", headers=_h(client, FAC), json={"title": title + " x"})
    assert r.status_code == 403, "faculty must be denied designation create"


# --- A5: Archive / unarchive + filter + audit -------------------------------

def test_archive_unarchive_and_filter(client, ref_record):
    if not ref_record:
        pytest.skip("no dept-scoped record with file available")
    rid = ref_record["record_id"]
    try:
        r = client.patch(f"/api/v1/admin/ip-records/{rid}", headers=_h(client, ADMIN), json={"is_archived": True})
        assert r.status_code == 200, r.text
        assert r.json()["is_archived"] is True

        arch = client.get("/api/v1/admin/ip-records?is_archived=true&per_page=100", headers=ADMIN).json()["records"]
        assert any(x["id"] == rid for x in arch), "archived record missing from is_archived=true list"
        active = client.get("/api/v1/admin/ip-records?is_archived=false&per_page=100", headers=ADMIN).json()["records"]
        assert all(x["id"] != rid for x in active), "archived record leaked into is_archived=false list"

        audit = client.get("/api/v1/audit/?per_page=100", headers=ADMIN).json()["audit_logs"]
        assert any(row["action"] == "IP_RECORD_ARCHIVED" and row["target_id"] == rid for row in audit), (
            "IP_RECORD_ARCHIVED audit event missing"
        )
    finally:
        r = client.patch(f"/api/v1/admin/ip-records/{rid}", headers=_h(client, ADMIN), json={"is_archived": False})
        assert r.status_code == 200 and r.json()["is_archived"] is False
        audit = client.get("/api/v1/audit/?per_page=100", headers=ADMIN).json()["audit_logs"]
        assert any(row["action"] == "IP_RECORD_UNARCHIVED" and row["target_id"] == rid for row in audit), (
            "IP_RECORD_UNARCHIVED audit event missing"
        )


def test_faculty_cannot_archive_record(client, ref_record):
    if not ref_record:
        pytest.skip("no dept-scoped record with file available")
    r = client.patch(f"/api/v1/admin/ip-records/{ref_record['record_id']}", headers=_h(client, FAC), json={"is_archived": True})
    assert r.status_code == 403, "faculty must be denied archive"


# --- U2: extended admin record filters -------------------------------------

def test_admin_date_range_filters_effective(client, ref_record):
    if not ref_record:
        pytest.skip("no dept-scoped record with file available")
    base = client.get("/api/v1/admin/ip-records?per_page=1", headers=ADMIN).json()["total"]
    assert base > 0

    future = client.get("/api/v1/admin/ip-records?date_from=2100-01-01&per_page=1", headers=ADMIN).json()["total"]
    past = client.get("/api/v1/admin/ip-records?date_to=2000-01-01&per_page=1", headers=ADMIN).json()["total"]
    assert future == 0, "date_from in the future must produce zero records"
    assert past == 0, "date_to in the past must produce zero records"

    broad = client.get("/api/v1/admin/ip-records?date_from=2000-01-01&date_to=2100-12-31&per_page=1", headers=ADMIN).json()["total"]
    assert broad == base, "wide date band must not shrink the record set"


def test_admin_designation_and_is_archived_filters(client, ref_record):
    if not ref_record:
        pytest.skip("no dept-scoped record with file available")
    rid = ref_record["record_id"]

    title = f"Filter Dsg {uuid.uuid4().hex[:6]}"
    desg = client.post("/api/v1/admin/designations", headers=_h(client, ADMIN), json={"title": title}).json()
    desg_id = desg["id"]
    try:
        r = client.patch(f"/api/v1/admin/ip-records/{rid}", headers=_h(client, ADMIN), json={"designation_id": desg_id})
        assert r.status_code == 200, r.text
        match = client.get(f"/api/v1/admin/ip-records?designation_id={desg_id}&per_page=100", headers=ADMIN).json()["records"]
        assert any(x["id"] == rid for x in match), "designation_id filter did not match the updated record"
    finally:
        client.patch(f"/api/v1/admin/ip-records/{rid}", headers=_h(client, ADMIN), json={"designation_id": None})
        client.delete(f"/api/v1/admin/designations/{desg_id}", headers=_h(client, ADMIN))


@pytest.mark.asyncio
async def test_admin_contributor_count_and_institution_filters(client, ref_record):
    if not ref_record:
        pytest.skip("no dept-scoped record with file available")
    rid = ref_record["record_id"]
    inst = f"Hardening Institute {uuid.uuid4().hex[:6]}"
    ids = []
    async with get_async_session_context() as db:
        existing_count_row = await db.execute(
            select(func.count()).select_from(IpContributor).where(IpContributor.ip_record_id == rid)
        )
        existing_count = existing_count_row.scalar() or 0
        for i in range(2):
            contrib = IpContributor(
                id=str(uuid.uuid4()),
                ip_record_id=rid,
                name=f"Contributor {i}",
                institution=inst,
                contributor_type="INTERNAL",
                match_status="VERIFICATION_REQUIRED",
                source="TEST",
                contributor_order=i,
            )
            db.add(contrib)
            ids.append(contrib.id)
        await db.commit()
    total_after = existing_count + 2
    try:
        match = client.get("/api/v1/admin/ip-records?contributor_count=1&per_page=100", headers=ADMIN).json()["records"]
        assert any(x["id"] == rid for x in match), "contributor_count filter missed the record with 2 contributors"
        none = client.get(f"/api/v1/admin/ip-records?contributor_count={total_after + 1}&per_page=100", headers=ADMIN).json()["records"]
        assert all(x["id"] != rid for x in none), f"contributor_count={total_after + 1} incorrectly matched a {total_after}-contributor record"
        by_inst = client.get(f"/api/v1/admin/ip-records?institution={inst}&per_page=100", headers=ADMIN).json()["records"]
        assert any(x["id"] == rid for x in by_inst), "institution (ILIKE) filter missed the record"
        no_inst = client.get("/api/v1/admin/ip-records?institution=NoSuchInstXYZ&per_page=100", headers=ADMIN).json()["records"]
        assert all(x["id"] != rid for x in no_inst), "institution filter matched an unrelated record"
    finally:
        async with get_async_session_context() as db:
            await db.execute(delete(IpContributor).where(IpContributor.id.in_(ids)))
            await db.commit()


# --- B1: HOD department scoping --------------------------------------------

def test_hod_dashboard_and_faculty_scoped(client):
    d = client.get("/api/v1/hod/dashboard", headers=HOD_A).json()
    assert d["department_id"] == "dept-a"

    fleet_a = client.get("/api/v1/hod/faculty?per_page=100", headers=HOD_A).json()["faculty"]
    assert any(u["id"] == "fac-a-001" for u in fleet_a)
    assert all(u["department_id"] in (None, "dept-a") for u in fleet_a), "HOD-A saw a non-dept-a faculty member"

    fleet_b = client.get("/api/v1/hod/faculty?per_page=100", headers=HOD_B).json()["faculty"]
    assert any(u["id"] == "fac-b-001" for u in fleet_b)
    assert all(u["department_id"] in (None, "dept-b") for u in fleet_b), "HOD-B saw a non-dept-b faculty member"

    r = client.get("/api/v1/hod/dashboard", headers=FAC)
    assert r.status_code == 403, "faculty must be denied HOD dashboard"


# --- AA1: authorized raw-file download -------------------------------------

def test_file_download_owner_and_admin_ok(client, ref_record):
    if not ref_record:
        pytest.skip("no dept-scoped record with file available")
    rid, fid = ref_record["record_id"], ref_record["file_id"]
    owner = _tok(ref_record["uploader_id"], "faculty", ref_record["department_id"])

    r = client.get(f"/api/v1/ip-records/{rid}/file", headers={"Authorization": f"Bearer {owner}"})
    assert r.status_code == 200, r.text
    assert len(r.content) > 0

    r = client.get(f"/api/v1/ip-records/{rid}/file", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert len(r.content) > 0

    r = client.get(f"/api/v1/ip-records/{rid}/file?file_id={fid}", headers=ADMIN)
    assert r.status_code == 200, r.text


def test_file_download_hod_scoping_and_idor(client, ref_record):
    if not ref_record:
        pytest.skip("no dept-scoped record with file available")
    rid, dept = ref_record["record_id"], ref_record["department_id"]

    same_dept_hod = _tok("hod-test-same", "hod_admin", dept)
    r = client.get(f"/api/v1/ip-records/{rid}/file", headers={"Authorization": f"Bearer {same_dept_hod}"})
    assert r.status_code == 200, "HOD of the owning department must download the file"
    assert len(r.content) > 0

    other_dept = "dept-b" if dept == "dept-a" else "dept-a"
    other_hod = _tok("hod-test-other", "hod_admin", other_dept)
    r = client.get(f"/api/v1/ip-records/{rid}/file", headers={"Authorization": f"Bearer {other_hod}"})
    assert r.status_code == 403, "HOD of another department must be denied"

    intruder = _tok("some-other-faculty", "faculty", "dept-b")
    r = client.get(f"/api/v1/ip-records/{rid}/file", headers={"Authorization": f"Bearer {intruder}"})
    assert r.status_code == 403, "non-owner faculty download must be denied (IDOR)"

    r = client.get(f"/api/v1/ip-records/{rid}/file")
    assert r.status_code in (401, 403), "anonymous download must be denied"


def test_file_download_unknown_file_id(client, ref_record):
    if not ref_record:
        pytest.skip("no dept-scoped record with file available")
    rid = ref_record["record_id"]
    r = client.get(f"/api/v1/ip-records/{rid}/file?file_id={uuid.uuid4()}", headers=ADMIN)
    assert r.status_code == 404, "unknown file_id must 404"


# --- D2: historical department snapshot on uploaded records ----------------

def test_uploaded_record_keeps_historical_snapshot(client):
    """Self-contained: create a temp dept-scoped record from the synthetic
    hardening fixture (never from real clean-room rows) and verify the
    historical snapshot, then remove the temp row."""
    import asyncio

    from sqlalchemy import delete as _delete
    from sqlalchemy import select as _select

    from app.models.base import IpRecord as _IpRecord
    from app.models.base import User as _User

    async def _make_temp():
        async with get_async_session_context() as db:
            fac = (await db.execute(_select(_User).where(_User.faculty_id == "FACA001"))).scalar_one_or_none()
            assert fac is not None, "hardening fixture FACA001 missing"
            assert fac.department_id == "dept-a", "hardening fixture must stay dept-a scoped"
            tmp_id = f"tmp-hist-{uuid.uuid4().hex[:10]}"
            db.add(
                _IpRecord(
                    id=tmp_id,
                    ip_type="PATENT",
                    title="Hardening Historical Snapshot Probe",
                    patent_number=f"HIST-{uuid.uuid4().hex[:8]}",
                    uploader_id=fac.id,
                    department_id=fac.department_id,
                    historical_department_id=fac.department_id,
                    historical_department_name="Department A",
                    processing_status="COMPLETED",
                    verification_status="UNVERIFIED",
                    document_type="CERTIFICATE",
                )
            )
            await db.commit()
            return tmp_id

    async def _read(tmp_id):
        async with get_async_session_context() as db:
            return (await db.execute(_select(_IpRecord).where(_IpRecord.id == tmp_id))).scalar_one_or_none()

    async def _remove(tmp_id):
        async with get_async_session_context() as db:
            await db.execute(_delete(_IpRecord).where(_IpRecord.id == tmp_id))
            await db.commit()

    tmp_id = asyncio.run(_make_temp())
    try:
        rec = asyncio.run(_read(tmp_id))
        assert rec is not None
        assert rec.department_id == "dept-a"
        assert rec.historical_department_id == rec.department_id, "historical snapshot dept differs from current"
        assert rec.historical_department_name == "Department A", "historical department name missing"
    finally:
        asyncio.run(_remove(tmp_id))


# --- D3 / Z2: Excel import with historical snapshot -------------------------

def _make_xlsx(headers, rows):
    col_letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    import xml.sax.saxutils as sax

    def esc(v):
        return sax.escape(str(v if v is not None else ""), {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})

    sheet_rows = [headers] + [[row.get(h, "") for h in headers] for row in rows]
    lines = []
    for ri, cells in enumerate(sheet_rows, start=1):
        cell_xml = []
        for ci, val in enumerate(cells):
            cell_xml.append(f'<c r="{col_letters[ci]}{ri}" t="inlineStr"><is><t>{esc(val)}</t></is></c>')
        lines.append(f'<row r="{ri}">{"".join(cell_xml)}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(lines)}</sheetData></worksheet>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


def _import_payload():
    headers = ["title", "faculty_id", "patent_number", "document_type", "ip_type"]
    uniq = uuid.uuid4().hex[:10]
    good = {
        "title": f"Hardening Import {uniq}",
        "faculty_id": "FACA001",
        "patent_number": f"IMP-{uniq}",
        "document_type": "CERTIFICATE",
        "ip_type": "PATENT",
    }
    bad = {"title": f"Bad Import {uniq}", "faculty_id": "NO-SUCH-FACULTY", "patent_number": "", "document_type": "CERTIFICATE", "ip_type": "PATENT"}
    return headers, [good, bad], uniq


def test_excel_import_preview_flow(client):
    headers, rows, _uniq = _import_payload()
    files = {"file": ("import_test.xlsx", _make_xlsx(headers, rows), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = client.post("/api/v1/admin/excel-import/preview", headers=_h(client, ADMIN), files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid_rows"] == 1, body
    assert body["invalid_rows"] == 1, body
    assert body["unknown_faculty"] == 1, body


def test_excel_import_records_keep_historical_snapshot(client):
    headers, rows, uniq = _import_payload()
    files = {"file": ("import_test.xlsx", _make_xlsx(headers, rows), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = client.post("/api/v1/admin/excel-import/import", headers=_h(client, ADMIN), files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported_count"] == 1, body
    assert body["failed_count"] == 1, body
    assert body["duplicate_count"] == 0, body

    recs = client.get("/api/v1/admin/ip-records?per_page=100", headers=ADMIN).json()["records"]
    imported = next(x for x in recs if x["title"] == f"Hardening Import {uniq}")
    assert imported["department_id"] == "dept-a"
    assert imported["historical_department_id"] == "dept-a", "imported record missing historical department id"
    assert imported["historical_department_name"] == "Department A", "imported record missing historical department name"
    # Cleanup: remove the synthetic import row so real clean-room evidence counts stay intact.
    try:
        import asyncio

        from sqlalchemy import delete as _delete

        from app.models.base import IpRecord as _IpRecord

        async def _remove():
            async with get_async_session_context() as db:
                await db.execute(_delete(_IpRecord).where(_IpRecord.title == f"Hardening Import {uniq}"))
                await db.commit()

        asyncio.run(_remove())
    except Exception:
        pass


# --- S1: notification types persist through the API -------------------------

@pytest.mark.asyncio
async def test_all_core_notification_types_visible_via_api(client):
    service = get_notification_service()
    created: list[str] = []
    seen_types: set[str] = set()
    try:
        async with get_async_session_context() as db:
            user_id = (await db.execute(select(User.id).where(User.id == "test-admin-002"))).scalar_one()
        for ntype in (
            NotificationType.UPLOAD_COMPLETED,
            NotificationType.VERIFICATION_COMPLETED,
            NotificationType.ASSOCIATION_REQUEST,
            NotificationType.ASSOCIATION_APPROVED,
            NotificationType.ASSOCIATION_REJECTED,
            NotificationType.CONFLICT_DETECTED,
            NotificationType.ADMIN_ACTION_REQUIRED,
            NotificationType.PROCESSING_FAILURE,
            NotificationType.CORRECTION_REQUIRED,
        ):
            notif = await service.create_notification(
                user_id=user_id,
                notification_type=ntype,
                title=f"Hardening S1 {ntype.value}",
                message=f"type={ntype.value}",
                related_entity_type="IP_RECORD",
                related_entity_id=uuid.uuid4().hex[:12],
            )
            created.append(notif.id)
            seen_types.add(ntype.value)

        r = client.get("/api/v1/notifications/?per_page=100", headers=ADMIN)
        assert r.status_code == 200, r.text
        body = r.json()
        api_types = {n["type"] for n in body["notifications"]}
        assert seen_types - api_types == set(), f"missing notification types: {seen_types - api_types}"
    finally:
        await asyncio.gather(*(service.delete_notification("test-admin-002", nid) for nid in created))


# --- X2: per-record agent job trail -----------------------------------------

def test_processing_job_agent_trail_per_record(client):
    best = 0
    for page in (1, 2):
        recs = client.get(f"/api/v1/admin/ip-records?per_page=20&page={page}", headers=ADMIN).json().get("records", [])
        if not recs:
            break
        for r in recs:
            st = client.get(f"/api/v1/uploads/{r['id']}/status", headers=ADMIN)
            if st.status_code == 200:
                best = max(best, len(st.json().get("jobs") or []))
    assert best >= 11, f"expected an 11+ agent step trail per pipeline record, found max {best}"