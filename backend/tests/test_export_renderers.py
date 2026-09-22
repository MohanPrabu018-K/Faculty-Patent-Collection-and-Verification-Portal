"""Unit tests for export renderers + download filename mapping (Issues 2 & 3).

Pure unit tests (no DB, no network): CSV validity, format/field selection,
genuine per-format output, date-only grant dates, and the excel->xlsx
download extension mapping.
"""
import csv
import io
import json
import zipfile
from datetime import datetime

from app.api.search_analytics_exports import _EXPORT_FILENAME_EXT
from app.services import export_renderers as renderers


class _FakeRecord:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", "rec-1")
        self.ip_type = kwargs.get("ip_type", "PATENT")
        self.patent_number = kwargs.get("patent_number", "P123")
        self.design_number = kwargs.get("design_number", "")
        self.application_number = kwargs.get("application_number", "")
        self.title = kwargs.get("title", "Some Invention")
        self.grant_date = kwargs.get("grant_date", datetime(2024, 10, 22, 0, 0, 0))
        self.filing_date = kwargs.get("filing_date", datetime(2024, 1, 5, 0, 0, 0))
        self.applicant = kwargs.get("applicant", "Applicant")
        self.patentee = kwargs.get("patentee", "")
        self.verification_status = kwargs.get("verification_status", "VERIFIED")
        self.processing_status = kwargs.get("processing_status", "COMPLETED")
        self.workflow_state = kwargs.get("workflow_state", "GRANTED")
        self.created_at = kwargs.get("created_at", datetime(2024, 10, 23, 0, 0, 0))


def test_csv_is_valid_and_header_matches():
    out = renderers.render_csv([_FakeRecord()])
    rows = list(csv.reader(io.StringIO(out.decode("utf-8"))))
    assert rows[0] == renderers.FIELDNAMES
    assert len(rows) == 2


def test_selected_fields_are_respected():
    out = renderers.render_csv([_FakeRecord()], selected_fields=["title", "grant_date"])
    rows = list(csv.reader(io.StringIO(out.decode("utf-8"))))
    assert rows[0] == ["title", "grant_date"]
    assert rows[1][0] == "Some Invention"


def test_unknown_only_fields_fall_back_to_all():
    out = renderers.render_csv([_FakeRecord()], selected_fields=["nope"])
    rows = list(csv.reader(io.StringIO(out.decode("utf-8"))))
    assert rows[0] == renderers.FIELDNAMES


def test_grant_date_has_no_time_component():
    out = renderers.render_csv([_FakeRecord()])
    rows = list(csv.reader(io.StringIO(out.decode("utf-8"))))
    idx = rows[0].index("grant_date")
    assert rows[1][idx] == "2024-10-22"
    assert "T" not in rows[1][idx]


def test_grant_date_empty_when_missing():
    out = renderers.render_csv([_FakeRecord(grant_date=None)])
    rows = list(csv.reader(io.StringIO(out.decode("utf-8"))))
    idx = rows[0].index("grant_date")
    assert rows[1][idx] == ""


def test_xlsx_is_a_real_zip_with_headers():
    out = renderers.render_xlsx([_FakeRecord()], selected_fields=["title"])
    assert out[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(out)) as zf:
        sheet = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "title" in sheet
    assert "Some Invention" in sheet


def test_pdf_and_docx_and_txt_generate():
    pdf = renderers.render_pdf([_FakeRecord()])
    assert pdf.startswith(b"%PDF")
    docx = renderers.render_docx([_FakeRecord()])
    assert docx[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(docx)) as zf:
        doc = zf.read("word/document.xml").decode("utf-8")
    assert "Some Invention" in doc
    txt = renderers.render_txt([_FakeRecord()]).decode("utf-8")
    assert "grant_date: 2024-10-22" in txt


def test_formats_produce_distinct_bytes():
    recs = [_FakeRecord()]
    outputs = {
        renderers.render_csv(recs),
        renderers.render_json(recs),
        renderers.render_xlsx(recs),
        renderers.render_pdf(recs),
        renderers.render_docx(recs),
        renderers.render_txt(recs),
    }
    assert len(outputs) == 6


def test_json_payload_shape():
    payload = json.loads(renderers.render_json([_FakeRecord()]).decode("utf-8"))
    assert payload["record_count"] == 1
    assert payload["records"][0]["grant_date"] == "2024-10-22"


def test_download_extension_mapping():
    assert _EXPORT_FILENAME_EXT["excel"] == "xlsx"
    assert _EXPORT_FILENAME_EXT["csv"] == "csv"
    assert _EXPORT_FILENAME_EXT["pdf"] == "pdf"
    assert _EXPORT_FILENAME_EXT["docx"] == "docx"
    assert _EXPORT_FILENAME_EXT["txt"] == "txt"
