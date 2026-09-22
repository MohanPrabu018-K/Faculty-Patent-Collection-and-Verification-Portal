from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import UTC, datetime
from typing import Any, Iterable
from xml.sax.saxutils import escape

FIELDNAMES = [
    "id",
    "ip_type",
    "patent_number",
    "design_number",
    "application_number",
    "title",
    "grant_date",
    "filing_date",
    "applicant",
    "patentee",
    "verification_status",
    "processing_status",
    "workflow_state",
    "faculty_name",
    "faculty_id",
    "department",
    "designation",
    "created_at",
]

ALL_FIELD_KEYS = set(FIELDNAMES)


def _date_only(value: Any) -> str:
    """Format a stored datetime as a calendar date (YYYY-MM-DD) for display.

    Grant dates are stored as midnight datetimes; exports must show the date
    without a time component. The underlying value is untouched — this is
    presentation formatting only.
    """
    if value is None or value == "":
        return ""
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else text


def _row_from_record(record: Any) -> dict[str, str]:
    """Map an IpRecord ORM row to a flat export dict (str values only)."""
    return {
        "id": record.id or "",
        "ip_type": record.ip_type or "",
        "patent_number": record.patent_number or "",
        "design_number": record.design_number or "",
        "application_number": record.application_number or "",
        "title": record.title or "",
        "grant_date": _date_only(getattr(record, "grant_date", None)),
        "filing_date": record.filing_date.isoformat() if getattr(record, "filing_date", None) else "",
        "applicant": getattr(record, "applicant", None) or getattr(record, "patentee", None) or "",
        "patentee": getattr(record, "patentee", None) or "",
        "verification_status": record.verification_status or "",
        "processing_status": record.processing_status or "",
        "workflow_state": getattr(record, "workflow_state", None) or "",
        "faculty_name": "",
        "faculty_id": "",
        "department": "",
        "designation": "",
        "created_at": record.created_at.isoformat() if record.created_at else "",
    }


def _filter_fields(row: dict[str, str], selected_fields: list[str] | None = None) -> dict[str, str]:
    """Filter a row to only the selected fields. If None, return all fields."""
    if not selected_fields:
        return row
    valid = [f for f in selected_fields if f in ALL_FIELD_KEYS]
    if not valid:
        return row
    return {k: v for k, v in row.items() if k in valid}


def _get_fieldnames(selected_fields: list[str] | None = None) -> list[str]:
    """Return fieldnames list, optionally filtered to selected fields."""
    if not selected_fields:
        return FIELDNAMES
    valid = [f for f in selected_fields if f in ALL_FIELD_KEYS]
    return valid if valid else FIELDNAMES


def _records_to_rows(records: Iterable[Any], selected_fields: list[str] | None = None) -> list[dict[str, str]]:
    return [_filter_fields(_row_from_record(r), selected_fields) for r in records]


# --- CSV ---


def render_csv(records: Iterable[Any], selected_fields: list[str] | None = None) -> bytes:
    fieldnames = _get_fieldnames(selected_fields)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in _records_to_rows(records, selected_fields):
        writer.writerow(row)
    return output.getvalue().encode("utf-8")


# --- JSON ---


def render_json(records: Iterable[Any], selected_fields: list[str] | None = None) -> bytes:
    payload = {
        "exported_at": datetime.now(UTC).isoformat(),
        "record_count": 0,
        "records": [],
    }
    rows = _records_to_rows(records, selected_fields)
    payload["record_count"] = len(rows)
    payload["records"] = rows
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


# --- Text (.txt, human-readable field/value format) ---


def render_txt(records: Iterable[Any], selected_fields: list[str] | None = None) -> bytes:
    fieldnames = _get_fieldnames(selected_fields)
    rows = _records_to_rows(records, selected_fields)
    lines = [
        "IP Records Export",
        f"Records: {len(rows)}",
        "",
    ]
    for index, row in enumerate(rows, start=1):
        lines.append(f"--- Record {index} ---")
        for field in fieldnames:
            lines.append(f"{field}: {row.get(field, '')}")
        lines.append("")
    return "\n".join(lines).encode("utf-8")


# --- Excel (.xlsx) via stdlib zipfile ---

_COLUMN_LETTERS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z"]


def _xlsx_sheet_xml(rows: list[dict[str, str]], fieldnames: list[str] | None = None) -> str:
    fnames = fieldnames or FIELDNAMES
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        "<sheetData>",
    ]
    for row_idx, row in enumerate(rows, start=1):
        cells = [f'<row r="{row_idx}">']
        for col_idx, field in enumerate(fnames, start=1):
            value = escape(str(row.get(field, "")))
            ref = f"{_COLUMN_LETTERS[col_idx - 1]}{row_idx}"
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>')
        cells.append("</row>")
        parts.append("".join(cells))
    parts.append("</sheetData>")
    parts.append("</worksheet>")
    return "".join(parts)


def _xlsx_zip_bytes(sheet_xml: str) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as zf:
        content_types = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
            '<Default Extension="xml" ContentType="application/xml"/>',
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>',
            "</Types>",
        ]
        zf.writestr("[Content_Types].xml", "".join(content_types))
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            "<sheets><sheet name=\"IPRecords\" sheetId=\"1\" r:id=\"rId1\"/></sheets>"
            "</workbook>",
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return stream.getvalue()


def render_xlsx(records: Iterable[Any], selected_fields: list[str] | None = None) -> bytes:
    fieldnames = _get_fieldnames(selected_fields)
    rows = _records_to_rows(records, selected_fields)
    sheet = _xlsx_sheet_xml([{f: f for f in fieldnames}] + rows, fieldnames)
    return _xlsx_zip_bytes(sheet)


# --- PDF (minimal, zero-dependency, Courier, ASCII-safe) ---

_PDF_PAGE_WIDTH = 612
_PDF_PAGE_HEIGHT = 792
_PDF_MARGIN_LEFT = 36
_PDF_MARGIN_TOP = 770
_PDF_LINE_HEIGHT = 12
_PDF_CHARS_PER_LINE = 118


def _pdf_escape(text: str) -> str:
    return (
        text.encode("latin-1", "replace")
        .decode("latin-1")
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def _pdf_render_pdf(records: list[dict[str, str]], fieldnames: list[str] | None = None) -> bytes:
    fnames = fieldnames or FIELDNAMES
    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_PDF_PAGE_WIDTH} {_PDF_PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ).encode("latin-1")
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")

    lines: list[str] = []
    header = " | ".join(fnames)
    lines.append(header)
    lines.append("-" * len(header))
    for row in records:
        lines.append(" | ".join(row.get(f, "") for f in fnames))
    lines.append("")
    lines.append(f"Exported: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')} — records: {len(records)}")

    stream_lines: list[str] = [f"BT /F1 9 Tf {_PDF_MARGIN_LEFT} {_PDF_MARGIN_TOP} Td 12 TL"]
    for line in lines:
        stream_lines.append(f"({_pdf_escape(line[: _PDF_CHARS_PER_LINE * 2])}) Tj T*")
    stream_lines.append("ET")
    stream_content = "\n".join(stream_lines).encode("latin-1")

    objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream_content), stream_content))

    output = io.BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets: list[int] = []
    for idx, obj in enumerate(objects, start=1):
        offsets.append(output.tell())
        output.write(b"%d 0 obj\n" % idx)
        output.write(obj)
        output.write(b"\nendobj\n")
    xref_pos = output.tell()
    output.write(b"xref\n0 %d\n" % (len(objects) + 1))
    output.write(b"0000000000 65535 f \n")
    for off in offsets:
        output.write(b"%010d 00000 n \n" % off)
    output.write(
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref_pos)
    )
    return output.getvalue()


def render_pdf(records: Iterable[Any], selected_fields: list[str] | None = None) -> bytes:
    fieldnames = _get_fieldnames(selected_fields)
    rows = _records_to_rows(records, selected_fields)
    return _pdf_render_pdf(rows, fieldnames)


# --- Word (.docx) via stdlib zipfile (Office Open XML, no paid deps) ---

def _docx_paragraph(text: str) -> str:
    return f"<w:p><w:r><w:t xml:space=\"preserve\">{escape(text)}</w:t></w:r></w:p>"


def render_docx(records: Iterable[Any], selected_fields: list[str] | None = None) -> bytes:
    fieldnames = _get_fieldnames(selected_fields)
    rows = _records_to_rows(records, selected_fields)
    paras = [_docx_paragraph("IP Records Export"), _docx_paragraph(f"Records: {len(rows)}  Exported: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}")]
    paras.append(_docx_paragraph(" | ".join(fieldnames)))
    for row in rows:
        paras.append(_docx_paragraph(" | ".join(row.get(f, "") for f in fieldnames)))
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>" + "".join(paras) + "</w:body></w:document>"
    )
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>")
        zf.writestr("_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>")
        zf.writestr("word/document.xml", document_xml)
    return stream.getvalue()