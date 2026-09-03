from __future__ import annotations

import io
import uuid
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_super_admin
from app.core.database import get_async_session
from app.core.exceptions import PortalError
from app.core.logging import log_audit
from app.models.base import IpRecord, User

router = APIRouter(prefix="/api/v1/admin/excel-import", tags=["excel-import"], dependencies=[Depends(require_super_admin)])

_NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


@dataclass
class ImportRow:
    row_num: int
    data: dict[str, str]
    errors: list[str]
    unknown_faculty: bool = False


def _col_name(cell_ref: str) -> str:
    return "".join(ch for ch in cell_ref if ch.isalpha())


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        with zf.open("xl/sharedStrings.xml") as f:
            tree = ET.parse(f)
    except KeyError:
        return []
    shared: list[str] = []
    for si in tree.getroot().findall("main:si", _NS):
        parts = [node.text or "" for node in si.iterfind('.//main:t', _NS)]
        shared.append("".join(parts))
    return shared


def _parse_xlsx_rows(file_bytes: bytes) -> list[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        shared = _shared_strings(zf)
        with zf.open("xl/worksheets/sheet1.xml") as f:
            tree = ET.parse(f)

    raw_rows: list[dict[str, str]] = []
    for row in tree.getroot().findall(".//main:sheetData/main:row", _NS):
        parsed: dict[str, str] = {}
        for cell in row.findall("main:c", _NS):
            col = _col_name(cell.attrib.get("r", ""))
            cell_type = cell.attrib.get("t")
            value = cell.findtext("main:v", default="", namespaces=_NS) or ""
            if cell_type == "s" and value.isdigit():
                idx = int(value)
                value = shared[idx] if idx < len(shared) else ""
            elif cell_type == "inlineStr":
                value = "".join(node.text or "" for node in cell.iterfind('.//main:t', _NS))
            parsed[col] = value.strip()
        if parsed:
            raw_rows.append(parsed)

    if not raw_rows:
        return []

    header_row = raw_rows[0]
    headers_by_col = {col: value.strip().lower() for col, value in header_row.items() if value.strip()}
    rows: list[dict[str, str]] = [headers_by_col]
    for raw in raw_rows[1:]:
        mapped = {headers_by_col.get(col, col).lower(): value for col, value in raw.items()}
        rows.append(mapped)
    return rows


async def _resolve_faculty(db: AsyncSession, faculty_id: str) -> User | None:
    return (await db.execute(select(User).where(User.faculty_id == faculty_id))).scalar_one_or_none()


@router.post("/preview", status_code=status.HTTP_200_OK)
async def preview_import(current_user: dict = Depends(get_current_user), file: UploadFile = File(...), db: AsyncSession = Depends(get_async_session)):
    if not file.filename.lower().endswith(".xlsx"):
        raise PortalError(message="Only .xlsx files are supported", error_code="VALIDATION_ERROR", status_code=400)
    rows = _parse_xlsx_rows(await file.read())
    if len(rows) < 2:
        raise PortalError(message="Workbook has no data rows", error_code="VALIDATION_ERROR", status_code=400)

    headers = list(rows[0].values())
    row_items: list[ImportRow] = []
    for idx, raw in enumerate(rows[1:], start=2):
        data = {k.lower(): v for k, v in raw.items()}
        errs: list[str] = []
        for field in ("title", "faculty_id", "document_type"):
            if not data.get(field):
                errs.append(f"Missing {field}")
        faculty = data.get("faculty_id", "")
        faculty_exists = bool(faculty and await _resolve_faculty(db, faculty))
        if faculty and not faculty_exists:
            errs.append("Invalid Faculty ID")
        row_items.append(ImportRow(row_num=idx, data=data, errors=errs, unknown_faculty=bool(faculty and not faculty_exists)))

    return {
        "headers": headers,
        "total_rows": len(rows) - 1,
        "valid_rows": len([r for r in row_items if not r.errors]),
        "invalid_rows": len([r for r in row_items if r.errors]),
        "unknown_faculty": len([r for r in row_items if r.unknown_faculty]),
        "rows": [{"row_num": r.row_num, "data": r.data, "errors": r.errors, "unknown_faculty": r.unknown_faculty} for r in row_items],
    }


@router.post("/import", status_code=status.HTTP_200_OK)
async def import_xlsx(current_user: dict = Depends(get_current_user), file: UploadFile = File(...), db: AsyncSession = Depends(get_async_session)):
    if not file.filename.lower().endswith(".xlsx"):
        raise PortalError(message="Only .xlsx files are supported", error_code="VALIDATION_ERROR", status_code=400)
    rows = _parse_xlsx_rows(await file.read())
    if len(rows) < 2:
        raise PortalError(message="Workbook has no data rows", error_code="VALIDATION_ERROR", status_code=400)

    created = skipped = failed = duplicates = 0
    job_id = str(current_user.get("id"))
    log_audit(actor=current_user.get("id"), action="EXCEL_IMPORT_STARTED", target_type="import_job", target_id=job_id, status="started", extra={"filename": file.filename})

    async with db.begin():
        for raw in rows[1:]:
            data = {k.lower(): v for k, v in raw.items()}
            title = data.get("title")
            faculty_id = data.get("faculty_id")
            if not title or not faculty_id:
                failed += 1
                continue
            faculty = await _resolve_faculty(db, faculty_id)
            if not faculty:
                failed += 1
                continue
            patent_number = data.get("patent_number")
            duplicate = None
            if patent_number:
                duplicate = (await db.execute(select(IpRecord).where(IpRecord.patent_number == patent_number))).scalar_one_or_none()
            if duplicate:
                duplicates += 1
                skipped += 1
                continue
            record = IpRecord(
                id=f"imp-{uuid.uuid4().hex[:12]}",
                ip_type=(data.get("ip_type") or "PATENT").upper(),
                title=title,
                patent_number=patent_number,
                design_number=data.get("design_number"),
                application_number=data.get("application_number"),
                uploader_id=faculty.id,
                department_id=faculty.department_id,
                designation_id=faculty.designation_id,
                processing_status="QUEUED",
                verification_status="UNVERIFIED",
                document_type=data.get("document_type") or "CERTIFICATE",
            )
            db.add(record)
            created += 1

    log_audit(actor=current_user.get("id"), action="EXCEL_IMPORT_COMPLETED", target_type="import_job", target_id=job_id, status="completed", extra={"created": created, "skipped": skipped, "failed": failed, "duplicates": duplicates})
    return {"imported_count": created, "skipped_count": skipped, "failed_count": failed, "duplicate_count": duplicates}
