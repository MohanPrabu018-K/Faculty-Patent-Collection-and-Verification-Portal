"""Regression tests for bugs fixed during the W2/compliance audit.

Covers:
1. Export renderers now emit genuinely distinct csv/json/xlsx/pdf bytes
   (previously every format silently returned CSV data).
2. The Faculty Identity Resolution agent no longer crashes when a
   contributor has no faculty match (`best_match=None`).
3. The `qr_data` API contract is a list (frontend + acceptance spec expect it).
"""
import io
import json
import zipfile
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agents.faculty_identity_agent import FacultyIdentityResolutionAgent
from app.api.faculty import _qr_data_list
from app.core.ai_contracts import AgentStatus, OrchestratorInput
from app.core.config import app_settings
from app.core.security import generate_jwt_token
from app.main import app
from app.services import export_renderers as er

client = TestClient(app)


def _tok(sub, role, dept="", fac=""):
    return generate_jwt_token(
        sub, app_settings.secret_key, app_settings.jwt_algorithm,
        minutes=30, email=f"{sub}@faculty.edu", role=role,
        faculty_id=fac or sub, department_id=dept, full_name=sub,
    )


ADMIN = {"Authorization": f"Bearer {_tok('test-admin-002', 'super_admin')}"}
FAC_A = {"Authorization": f"Bearer {_tok('fac-a-002', 'faculty', 'dept-a', 'FACA002')}"}
CSRF = {"X-CSRF-Token": "t"}


def _csrf_client():
    c = TestClient(app)
    c.cookies.set("csrf_token", "t")
    return c


def _sample_records():
    return [
        SimpleNamespace(
            id="rec-1",
            ip_type="DESIGN_REGISTRATION",
            patent_number=None,
            design_number="435272-001",
            application_number="123456",
            title="Artificial Intelligence based stress detection device",
            verification_status="VERIFICATION_REQUIRED",
            processing_status="COMPLETED",
            created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        ),
        SimpleNamespace(
            id="rec-2",
            ip_type="PATENT",
            patent_number="IN123456",
            design_number=None,
            application_number=None,
            title="A device with unicode: तनाव",
            verification_status="VERIFIED",
            processing_status="COMPLETED",
            created_at=None,
        ),
    ]


# --- W2: export renderers ---------------------------------------------------

def test_csv_renderer_outputs_csv_bytes():
    data = er.render_csv(_sample_records())
    text = data.decode("utf-8")
    header = text.splitlines()[0]
    assert "id" in header
    assert "patent_number" in header
    assert "title" in header
    assert "grant_date" in header
    assert "verification_status" in header
    assert "435272-001" in text


def test_json_renderer_outputs_json_document():
    data = er.render_json(_sample_records())
    payload = json.loads(data.decode("utf-8"))
    assert payload["record_count"] == 2
    assert payload["records"][0]["design_number"] == "435272-001"
    assert "id" in payload["records"][0]
    assert "grant_date" in payload["records"][0]
    assert "verification_status" in payload["records"][0]


def test_xlsx_renderer_outputs_real_xlsx_zip():
    data = er.render_xlsx(_sample_records())
    # xlsx = zip container
    assert data[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert "xl/worksheets/sheet1.xml" in names
        assert "[Content_Types].xml" in names
        sheet = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
        assert "435272-001" in sheet
        assert "<t>id</t>" in sheet  # header row present (first field name)


def test_pdf_renderer_outputs_real_pdf():
    data = er.render_pdf(_sample_records())
    assert data.startswith(b"%PDF-")
    assert b"startxref" in data
    assert b"/Type /Page" in data
    assert b"435272-001" in data


# --- W2: exports API end-to-end ---------------------------------------------

@pytest.mark.parametrize(
    "fmt, magic, check",
    [
        ("csv", b"id,ip_type", lambda d: True),
        ("json", b"{", lambda d: json.loads(d.decode("utf-8"))["record_count"] >= 0),
        ("excel", b"PK", lambda d: "xl/worksheets/sheet1.xml" in zipfile.ZipFile(io.BytesIO(d)).namelist()),
        ("pdf", b"%PDF-", lambda d: b"startxref" in d),
    ],
)
def test_export_api_returns_expected_content_type_and_bytes(fmt, magic, check):
    c = _csrf_client()
    r = c.post(f"/api/v1/exports/?format={fmt}", headers={**ADMIN, **CSRF}, json={})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    dl = c.get(f"/api/v1/exports/{job_id}/download", headers=ADMIN)
    assert dl.status_code == 200
    assert dl.content.startswith(magic), f"{fmt} content did not start with expected magic"
    assert check(dl.content)


def test_export_faculty_cannot_download_admin_export():
    c = _csrf_client()
    r = c.post("/api/v1/exports/?format=json", headers={**ADMIN, **CSRF}, json={})
    job_id = r.json()["job_id"]
    assert c.get(f"/api/v1/exports/{job_id}/download", headers=FAC_A).status_code == 403


# --- J1: identity agent with no faculty match does not crash ----------------

@pytest.mark.asyncio
async def test_faculty_identity_agent_external_contributor_no_crash(monkeypatch):
    from app.services import identity_resolution as ir_mod
    from app.services.identity_resolution import IdentityMatchResult

    class _FakeService:
        async def resolve_identity(self, **kwargs):
            return IdentityMatchResult(
                query_name=kwargs.get("extracted_name", ""),
                candidates=[],
                best_match=None,
                requires_human_review=True,
                review_reason="No matching faculty found",
            )

    monkeypatch.setattr(ir_mod, "IdentityResolutionService", _FakeService)
    agent = FacultyIdentityResolutionAgent()
    input_data = OrchestratorInput(
        upload_id="test-ext",
        file_data=b"",
        filename="test.pdf",
        context={
            "canonical_data": {
                "contributors": [
                    {"name": "External NonFaculty ZZ-99999", "institution": "External Corp"},
                ]
            }
        },
    )
    result = await agent.process(input_data)
    # Regression: previously raised AttributeError (None.get) and returned ERROR.
    assert result.status == AgentStatus.SUCCESS
    assert result.error is None
    assert result.recommendation is None
    assert result.extracted_data["resolved_entities"][0]["best_match"] is None


# --- G1: qr_data API contract is a list -------------------------------------

def test_qr_data_helper_normalizes():
    assert _qr_data_list(None) == []
    assert _qr_data_list("") == []
    assert _qr_data_list("QR-1") == ["QR-1"]


def test_my_records_qr_data_is_list():
    r = client.get("/api/v1/faculty/my-records", headers=FAC_A)
    assert r.status_code == 200
    for rec in r.json()["records"]:
        assert isinstance(rec.get("qr_data"), list)


def test_status_qr_data_is_list():
    dash = client.get("/api/v1/faculty/dashboard", headers=FAC_A)
    assert dash.status_code == 200
    recs = dash.json().get("recent_records", [])
    if not recs:
        pytest.skip("Faculty A has no records in the staging DB")
    rid = recs[0]["id"]
    status = client.get(f"/api/v1/faculty/{rid}/status", headers=FAC_A)
    assert status.status_code == 200
    assert isinstance(status.json().get("qr_data"), list)