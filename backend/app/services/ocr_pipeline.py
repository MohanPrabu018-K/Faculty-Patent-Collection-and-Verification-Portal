from __future__ import annotations

import io
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class OCRPageResult:
    page_number: int
    text: str = ""
    confidence: float = 0.0
    source: str = "unknown"
    warnings: list[str] = field(default_factory=list)


@dataclass
class OCRResult:
    success: bool
    text: str
    pages: list[OCRPageResult] = field(default_factory=list)
    confidence: float = 0.0
    source: str = "unknown"
    warnings: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class QRResult:
    success: bool
    qr_data: list[str] = field(default_factory=list)
    source: str = "unknown"
    warnings: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DocumentProcessingResult:
    success: bool
    is_pdf: bool
    has_text_layer: bool
    ocr: OCRResult
    qr: QRResult
    warnings: list[str] = field(default_factory=list)


def _safe_import(name: str):
    try:
        return __import__(name, fromlist=["*"])
    except Exception:
        return None


def classify_document(text: str, filename: str) -> dict:
    """Deterministic keyword-based document classification (no AI/LLM)."""
    raw_text = text or ""
    text_lower = raw_text.lower()

    design_number_match = re.search(r'design\s*(?:number|no\.?|registration)\s*[:\-\s]*[A-Z0-9][A-Z0-9\-/]*', raw_text, re.IGNORECASE | re.DOTALL)
    patent_number_match = re.search(r'patent\s*(?:number|no\.?)\s*[:\-\s]*[A-Z0-9][A-Z0-9\-/]*', raw_text, re.IGNORECASE | re.DOTALL)
    application_number_match = re.search(r'application\s*(?:number|no\.?)\s*[:\-\s]*[A-Z0-9][A-Z0-9\-/]*', raw_text, re.IGNORECASE | re.DOTALL)

    strong_design_signals = [
        "design",
        "design number",
        "design no",
        "design registration",
        "registered design",
    ]
    strong_patent_signals = [
        "patent",
        "patent number",
        "patent no",
        "application number",
        "grant date",
        "inventor",
    ]

    design_score = sum(1 for kw in strong_design_signals if kw in text_lower) + (2 if design_number_match else 0)
    patent_score = sum(1 for kw in strong_patent_signals if kw in text_lower) + (2 if patent_number_match or application_number_match else 0)

    if design_number_match and design_score >= patent_score:
        return {"ip_type": "DESIGN_REGISTRATION", "confidence": min(0.9 + design_score * 0.03, 0.99)}
    if patent_number_match or application_number_match or patent_score > 0:
        return {"ip_type": "PATENT", "confidence": min(0.9 + patent_score * 0.03, 0.99)}
    return {"ip_type": "UNKNOWN_OTHER", "confidence": 0.5}


def perform_ocr(image_bytes: bytes) -> dict:
    """Run OCR on raw image bytes (PaddleOCR → Tesseract → optional OCR.Space)."""
    result = _ocr_image_bytes(image_bytes, page_number=1)
    return {
        "success": bool(result.text),
        "text": result.text,
        "average_confidence": result.confidence,
        "source": result.source,
        "warnings": result.warnings,
    }


def _load_pdf_text(path: Path) -> tuple[list[str], bool]:
    fitz = _safe_import("fitz")
    if fitz is None:
        return [], False
    pages: list[str] = []
    doc = fitz.open(path)
    try:
        for page in doc:
            pages.append((page.get_text("text") or "").strip())
    finally:
        doc.close()
    has_text = any(page.strip() for page in pages)
    return pages, has_text


def _image_to_rgb_np(image_bytes: bytes):
    """Decode image bytes to an RGB numpy array (PIL + numpy)."""
    import numpy as np
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes))
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    return np.array(image)


def _ocr_with_paddle(image_bytes: bytes, page_number: int = 1) -> OCRPageResult:
    """Primary OCR: PaddleOCR (local, open-source).

    Returns an empty result with a warning if paddle/paddleocr is unavailable.
    """
    warnings: list[str] = []
    try:
        from paddleocr import PaddleOCR
    except Exception as exc:  # pragma: no cover - dependency guard
        return OCRPageResult(
            page_number=page_number,
            text="",
            confidence=0.0,
            source="paddleocr",
            warnings=[f"PaddleOCR unavailable: {exc}"],
        )

    try:
        arr = _image_to_rgb_np(image_bytes)
        ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        result = ocr.ocr(arr, cls=True)
        lines: list[str] = []
        confidences: list[float] = []
        for page in result or []:
            for entry in page or []:
                if not entry:
                    continue
                text = entry[1][0] if len(entry) > 1 and entry[1] else ""
                conf = float(entry[1][1]) if len(entry) > 1 and len(entry[1]) > 1 else 0.0
                if text:
                    lines.append(str(text))
                    confidences.append(conf)
        text = "\n".join(lines).strip()
        avg_conf = (sum(confidences) / len(confidences)) if confidences else 0.0
    except Exception as exc:  # pragma: no cover - unexpected PaddleOCR error
        return OCRPageResult(
            page_number=page_number,
            text="",
            confidence=0.0,
            source="paddleocr",
            warnings=[f"PaddleOCR failed: {exc}"],
        )

    if not text:
        warnings.append("PaddleOCR produced no text for this page")

    return OCRPageResult(
        page_number=page_number,
        text=text,
        confidence=avg_conf,
        source="paddleocr",
        warnings=warnings,
    )


_TESSERACT_CMD_CACHE: str | None = None
_TESSERACT_RESOLVED = False

_COMMON_TESSERACT_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/opt/homebrew/bin/tesseract",
)


def _resolve_tesseract_cmd() -> str | None:
    """Locate the Tesseract binary: TESSERACT_CMD env → PATH → common install dirs.

    Result is cached; returns None when no local Tesseract binary is available.
    """
    global _TESSERACT_CMD_CACHE, _TESSERACT_RESOLVED
    if _TESSERACT_RESOLVED:
        return _TESSERACT_CMD_CACHE

    import shutil

    candidates: list[str] = []
    try:
        from app.core.config import local_ocr_settings

        if local_ocr_settings.tesseract_cmd:
            candidates.append(local_ocr_settings.tesseract_cmd)
    except Exception:
        pass

    which = shutil.which("tesseract")
    if which:
        candidates.append(which)
    candidates.extend(_COMMON_TESSERACT_PATHS)

    resolved = next((p for p in candidates if p and Path(p).is_file()), None)
    _TESSERACT_CMD_CACHE = resolved
    _TESSERACT_RESOLVED = True
    return resolved


def _tesseract_langs() -> str:
    try:
        from app.core.config import local_ocr_settings

        return local_ocr_settings.tesseract_langs or "eng"
    except Exception:
        return "eng"


def _ocr_with_tesseract(image_bytes: bytes, page_number: int = 1) -> OCRPageResult:
    """Tesseract OCR (local, open-source) — the guaranteed-local engine.

    Returns an empty result with a warning if pytesseract or the Tesseract
    binary is missing.
    """
    warnings: list[str] = []
    try:
        import pytesseract
    except Exception as exc:  # pragma: no cover - dependency guard
        return OCRPageResult(
            page_number=page_number,
            text="",
            confidence=0.0,
            source="tesseract",
            warnings=[f"Tesseract unavailable: {exc}"],
        )

    cmd = _resolve_tesseract_cmd()
    if not cmd:
        return OCRPageResult(
            page_number=page_number,
            text="",
            confidence=0.0,
            source="tesseract",
            warnings=[
                "Tesseract binary not found (set TESSERACT_CMD or install tesseract-ocr)"
            ],
        )
    pytesseract.pytesseract.tesseract_cmd = cmd

    try:
        arr = _image_to_rgb_np(image_bytes)
        lang = _tesseract_langs()
        text = (pytesseract.image_to_string(arr, lang=lang) or "").strip()
        data = pytesseract.image_to_data(arr, lang=lang, output_type=pytesseract.Output.DICT)
        conf_values = [int(c) for c in data.get("conf", []) if str(c).lstrip("-").isdigit()]
        avg_conf = (sum(conf_values) / len(conf_values) / 100.0) if conf_values else 0.0
    except Exception as exc:  # pragma: no cover - tesseract binary missing/error
        return OCRPageResult(
            page_number=page_number,
            text="",
            confidence=0.0,
            source="tesseract",
            warnings=[f"Tesseract OCR failed: {exc}"],
        )

    if not text:
        warnings.append("Tesseract produced no text for this page")

    return OCRPageResult(
        page_number=page_number,
        text=text,
        confidence=avg_conf,
        source="tesseract",
        warnings=warnings,
    )


_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_RETRYABLE_ERROR_HINTS = (
    "throttl",
    "rate limit",
    "concurrent",
    "timed out",
    "timeout",
    "try again",
    "temporarily",
)


def _ocr_with_ocrspace(image_bytes: bytes, page_number: int = 1) -> OCRPageResult:
    """Optional last-resort OCR.Space fallback (only when local OCR fails).

    OCR.Space is NOT the primary engine and is optional. Retries HTTP 429 and
    transient (5xx / network / throttle) failures with a linear backoff.
    """
    import base64

    try:
        import httpx
        from app.core.config import ocr_space_settings
    except Exception as exc:  # pragma: no cover - dependency guard
        return OCRPageResult(
            page_number=page_number,
            text="",
            confidence=0.0,
            source="ocr_space",
            warnings=[f"OCR.Space client unavailable: {exc}"],
        )

    if not ocr_space_settings.api_key:
        return OCRPageResult(
            page_number=page_number,
            text="",
            confidence=0.0,
            source="ocr_space",
            warnings=["OCR.Space API key is not configured"],
        )

    max_attempts = max(1, int(getattr(ocr_space_settings, "max_retries", 3)))
    backoff = max(0.0, float(getattr(ocr_space_settings, "backoff_seconds", 2.0)))

    last_warnings: list[str] = []
    for attempt in range(1, max_attempts + 1):
        try:
            b64 = base64.b64encode(image_bytes).decode("ascii")
            response = httpx.post(
                ocr_space_settings.api_url,
                data={
                    "apikey": ocr_space_settings.api_key,
                    "language": ocr_space_settings.language,
                    "OCREngine": ocr_space_settings.ocr_engine,
                    "isOverlayRequired": "false",
                    "base64Image": f"data:image/png;base64,{b64}",
                },
                timeout=ocr_space_settings.timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_warnings = [f"OCR.Space request failed (attempt {attempt}): {exc}"]
            if attempt < max_attempts and backoff:
                time.sleep(backoff * attempt)
            continue
        except Exception as exc:  # pragma: no cover - unexpected client error
            return OCRPageResult(
                page_number=page_number,
                text="",
                confidence=0.0,
                source="ocr_space",
                warnings=[f"OCR.Space request error (attempt {attempt}): {exc}"],
            )

        if response.status_code in _RETRYABLE_STATUS:
            last_warnings = [f"OCR.Space HTTP {response.status_code} (attempt {attempt})"]
            if attempt < max_attempts and backoff:
                time.sleep(backoff * attempt)
            continue

        try:
            response.raise_for_status()
        except Exception as exc:
            return OCRPageResult(
                page_number=page_number,
                text="",
                confidence=0.0,
                source="ocr_space",
                warnings=[f"OCR.Space HTTP error (attempt {attempt}): {exc}"],
            )

        try:
            payload = response.json()
        except Exception as exc:
            return OCRPageResult(
                page_number=page_number,
                text="",
                confidence=0.0,
                source="ocr_space",
                warnings=[f"OCR.Space returned non-JSON body (attempt {attempt}): {exc}"],
            )

        parsed = (payload.get("ParsedResults") or [{}])[0]
        text = (parsed.get("ParsedText") or "").strip()
        exit_code = int((parsed.get("FileParseExitCode") or 1))
        errored = bool(payload.get("IsErroredOnProcessing"))
        if exit_code != 1 or errored:
            raw_err = payload.get("ErrorMessage") or parsed.get("ErrorMessage") or parsed.get("ParsedText") or "OCR.Space processing error"
            err_text = raw_err if isinstance(raw_err, str) else "; ".join(str(x) for x in raw_err)
            last_warnings = [err_text]
            should_retry = any(hint in err_text.lower() for hint in _RETRYABLE_ERROR_HINTS)
            if should_retry and not text and attempt < max_attempts:
                if backoff:
                    time.sleep(backoff * attempt)
                continue
            return OCRPageResult(
                page_number=page_number,
                text=text,
                confidence=1.0 if text else 0.0,
                source="ocr_space",
                warnings=last_warnings,
            )

        return OCRPageResult(
            page_number=page_number,
            text=text,
            confidence=1.0 if text else 0.0,
            source="ocr_space",
            warnings=[],
        )

    warnings = list(last_warnings)
    warnings.append(f"OCR.Space retries exhausted after {max_attempts} attempt(s)")
    return OCRPageResult(
        page_number=page_number,
        text="",
        confidence=0.0,
        source="ocr_space",
        warnings=warnings,
    )


def _ocr_image_bytes(image_bytes: bytes, page_number: int = 1) -> OCRPageResult:
    """OCR a single image with the local-first, ₹0-cost engine chain:

    PaddleOCR (optional) → Tesseract (local, always available when installed)
    → OCR.Space (optional emergency fallback, disabled via
    OCRSPACE_FALLBACK_ENABLED=false or by leaving OCRSPACE_API_KEY empty).

    Local/open-source engines are always tried first. The external provider is
    only consulted when every local engine fails to produce text *and* it is
    explicitly enabled — it is never required for normal operation.
    """
    local_warnings: list[str] = []
    for engine in (_ocr_with_paddle, _ocr_with_tesseract):
        result = engine(image_bytes, page_number)
        local_warnings.extend(result.warnings)
        if result.text.strip():
            return result

    skip_reason: str | None = None
    try:
        from app.core.config import local_ocr_settings, ocr_space_settings

        if not local_ocr_settings.ocrspace_fallback_enabled:
            skip_reason = "external OCR fallback disabled (OCRSPACE_FALLBACK_ENABLED=false)"
        elif not ocr_space_settings.api_key:
            skip_reason = "external OCR (OCR.Space) not configured; skipped"
    except Exception:
        skip_reason = "external OCR fallback unavailable"

    if skip_reason is not None:
        return OCRPageResult(
            page_number=page_number,
            text="",
            confidence=0.0,
            source="none",
            warnings=list(dict.fromkeys(local_warnings + [skip_reason])),
        )

    external = _ocr_with_ocrspace(image_bytes, page_number)
    return OCRPageResult(
        page_number=page_number,
        text=external.text,
        confidence=external.confidence,
        source=external.source if external.text else "none",
        warnings=list(dict.fromkeys(local_warnings + external.warnings)),
    )


def process_document(file_bytes: bytes, filename: str | None = None) -> DocumentProcessingResult:
    suffix = (Path(filename).suffix.lower() if filename else "").lower()
    is_pdf = suffix == ".pdf" or file_bytes.startswith(b"%PDF")
    warnings: list[str] = []
    evidence: list[dict[str, Any]] = []

    if is_pdf:
        fitz = _safe_import("fitz")
        if fitz is None:
            warnings.append("PyMuPDF unavailable; falling back to image OCR where possible")
            page_result = _ocr_image_bytes(file_bytes)
            return DocumentProcessingResult(
                success=bool(page_result.text),
                is_pdf=True,
                has_text_layer=False,
                ocr=OCRResult(
                    success=bool(page_result.text),
                    text=page_result.text,
                    pages=[page_result],
                    confidence=page_result.confidence,
                    source=page_result.source,
                    warnings=page_result.warnings,
                    evidence=[{"page": page_result.page_number, "source": page_result.source, "confidence": page_result.confidence}],
                ),
                qr=decode_qr_payloads(file_bytes, filename=filename),
                warnings=warnings,
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / (filename or "input.pdf")
            pdf_path.write_bytes(file_bytes)
            page_texts, has_text_layer = _load_pdf_text(pdf_path)
            if has_text_layer:
                pages: list[OCRPageResult] = [
                    OCRPageResult(page_number=i + 1, text=text, confidence=1.0 if text.strip() else 0.0, source="embedded_text")
                    for i, text in enumerate(page_texts)
                ]
                text = "\n\n".join([page.text for page in pages if page.text]).strip()
                evidence.extend({"page": page.page_number, "source": page.source, "confidence": page.confidence} for page in pages if page.text)
                return DocumentProcessingResult(
                    success=bool(text),
                    is_pdf=True,
                    has_text_layer=True,
                    ocr=OCRResult(success=bool(text), text=text, pages=pages, confidence=1.0 if text else 0.0, source="embedded_text", evidence=list(evidence), warnings=[]),
                    qr=decode_qr_payloads(file_bytes, filename=filename),
                    warnings=warnings,
                )

            doc = fitz.open(pdf_path)
            pages: list[OCRPageResult] = []
            try:
                for index, page in enumerate(doc, start=1):
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    img_bytes = pix.tobytes("png")
                    page_result = _ocr_image_bytes(img_bytes, page_number=index)
                    pages.append(page_result)
            finally:
                doc.close()

        text = "\n\n".join([page.text for page in pages if page.text]).strip()
        evidence.extend({"page": page.page_number, "source": page.source, "confidence": page.confidence} for page in pages if page.text)
        page_sources = [p.source for p in pages if p.text]
        ocr_source = page_sources[0] if len(set(page_sources)) == 1 else (page_sources[0] if page_sources else "none")
        return DocumentProcessingResult(
            success=bool(text),
            is_pdf=True,
            has_text_layer=False,
            ocr=OCRResult(success=bool(text), text=text, pages=pages, confidence=sum(p.confidence for p in pages) / len(pages) if pages else 0.0, source=ocr_source, warnings=[warn for p in pages for warn in p.warnings], evidence=list(evidence)),
            qr=decode_qr_payloads(file_bytes, filename=filename),
            warnings=warnings,
        )

    page_result = _ocr_image_bytes(file_bytes)
    return DocumentProcessingResult(
        success=bool(page_result.text),
        is_pdf=False,
        has_text_layer=False,
        ocr=OCRResult(success=bool(page_result.text), text=page_result.text, pages=[page_result], confidence=page_result.confidence, source=page_result.source, warnings=page_result.warnings, evidence=[{"page": 1, "source": page_result.source, "confidence": page_result.confidence}]),
        qr=decode_qr_payloads(file_bytes, filename=filename),
        warnings=warnings,
    )


def decode_qr_payloads(file_bytes: bytes, filename: str | None = None) -> QRResult:
    warnings: list[str] = []
    evidence: list[dict[str, Any]] = []
    payloads: list[str] = []
    cv2 = _safe_import("cv2")
    pyzbar = _safe_import("pyzbar.pyzbar")
    pil = _safe_import("PIL.Image")
    fitz = _safe_import("fitz")

    if pil is None:
        return QRResult(success=False, qr_data=[], source="unavailable", warnings=["PIL unavailable"], evidence=[])

    image_sources: list[tuple[str, Any]] = []
    is_pdf = (Path(filename).suffix.lower() == ".pdf" if filename else file_bytes.startswith(b"%PDF"))

    try:
        if is_pdf and fitz is not None:
            with tempfile.TemporaryDirectory() as tmpdir:
                pdf_path = Path(tmpdir) / (filename or "input.pdf")
                pdf_path.write_bytes(file_bytes)
                doc = fitz.open(pdf_path)
                try:
                    for page_index, page in enumerate(doc, start=1):
                        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                        image_sources.append((f"pdf_page_{page_index}", pil.open(io.BytesIO(pix.tobytes("png")))))
                finally:
                    doc.close()
        else:
            image_sources.append(("original", pil.open(io.BytesIO(file_bytes))))
    except Exception as exc:
        warnings.append(f"QR source preparation failed: {exc}")
        try:
            image_sources.append(("original", pil.open(io.BytesIO(file_bytes))))
        except Exception as inner_exc:
            return QRResult(success=False, qr_data=[], source="none", warnings=warnings + [f"Image decode failed: {inner_exc}"], evidence=[])

    if cv2 is not None:
        try:
            import numpy as np
            arr = np.frombuffer(file_bytes, dtype=np.uint8)
            decoded = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if decoded is not None:
                gray = cv2.cvtColor(decoded, cv2.COLOR_BGR2GRAY)
                image_sources.append(("grayscale", pil.fromarray(gray)))
        except Exception as exc:
            warnings.append(f"OpenCV QR preprocessing skipped: {exc}")

    for label, candidate in image_sources:
        try:
            if pyzbar is not None:
                decoded = pyzbar.decode(candidate)
                for item in decoded:
                    payload = item.data.decode("utf-8", errors="replace").strip()
                    if payload and payload not in payloads:
                        payloads.append(payload)
                        evidence.append({"source": label, "type": item.type, "payload": payload})
                if payloads:
                    return QRResult(success=True, qr_data=payloads, source="pyzbar", warnings=warnings, evidence=evidence)
        except Exception as exc:
            warnings.append(f"QR decode skipped for {label}: {exc}")

        if cv2 is not None:
            try:
                detector = cv2.QRCodeDetector()
                data, _, _ = detector.detectAndDecode(candidate)
                if data and data not in payloads:
                    payloads.append(data)
                    evidence.append({"source": label, "type": "QRCodeDetector", "payload": data})
                    return QRResult(success=True, qr_data=payloads, source="opencv", warnings=warnings, evidence=evidence)
            except Exception as exc:
                warnings.append(f"OpenCV QR detector failed for {label}: {exc}")

    return QRResult(success=False, qr_data=[], source="none", warnings=warnings or ["No QR code detected"], evidence=evidence)

