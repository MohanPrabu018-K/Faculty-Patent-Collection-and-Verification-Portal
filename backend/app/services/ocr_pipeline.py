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


def _is_valid_url(value: str) -> bool:
    """Check if payload is a plausible URL (http/https with netloc)."""
    if not value or not isinstance(value, str):
        return False
    v = value.strip()
    if len(v) < 8:
        return False
    if not v.lower().startswith(("http://", "https://")):
        return False
    try:
        from urllib.parse import urlparse

        parsed = urlparse(v)
        return bool(parsed.netloc and "." in parsed.netloc)
    except Exception:
        return False


def _is_ip_india_url(value: str) -> bool:
    """Heuristic IP-India URL recognition without rejecting legitimate non-IP-India QRs."""
    if not _is_valid_url(value):
        return False
    try:
        from urllib.parse import urlparse

        host = urlparse(value).netloc.lower()
        # Accept primary and proxy variants
        return (
            "ipindia.gov.in" in host
            or "iprsearch" in host
            or "inpass" in host
            or "search.ipindia" in host
        )
    except Exception:
        return False


def _validate_qr_payload(payload: str) -> tuple[bool, str]:
    """Validate a decoded QR payload, returning (is_valid, reason)."""
    if payload is None:
        return False, "null payload"
    if not isinstance(payload, str):
        payload = str(payload)
    stripped = payload.strip()
    if not stripped:
        return False, "empty payload"
    if len(stripped) < 3:
        return False, "payload too short"
    # Allow any non-empty payload; URL validation is advisory, not rejecting
    return True, "ok"


def _prepare_qr_variants(image) -> list[tuple[str, Any]]:
    """Create deterministic variants for robust QR decoding (no paid deps)."""
    variants: list[tuple[str, Any]] = [("original", image)]
    try:
        # Bug 10: pyzbar decodes grayscale far more reliably than color.
        # Every source (including full-page PDF renders, which previously had
        # no grayscale variant at all) gets one.
        gray = image.convert("L") if hasattr(image, "convert") else image
        variants.append(("grayscale", gray))
        # Grayscale already handled via cv2 path; add rotated variants for practical deskew
        variants.append(("rotated_90", image.rotate(90, expand=True)))
        variants.append(("rotated_180", image.rotate(180, expand=True)))
        variants.append(("rotated_270", image.rotate(270, expand=True)))
        # Low-quality / small QR: 2x upscale via nearest/bilinear.
        # Bug 10: a full A4 page rendered at 2x matrix is ~1190x1684, so the
        # old <1200 gate skipped upscaling exactly where small on-page QRs
        # need it most. Gate at <2000 keeps cost to one extra decode.
        w, h = image.size
        if max(w, h) < 2000:
            variants.append(("upscaled_2x", image.resize((w * 2, h * 2))))
    except Exception:
        pass
    return variants


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
        "registration of design",
        "design act",
        "industrial design",
        "ornamental",
        "locarno",
    ]
    strong_patent_signals = [
        "patent",
        "patent number",
        "patent no",
        "application number",
        "grant date",
        "date of grant",
        "inventor",
        "patentee",
        "claims",
        "specification",
    ]

    design_score = sum(1 for kw in strong_design_signals if kw in text_lower) + (2 if design_number_match else 0)
    patent_score = sum(1 for kw in strong_patent_signals if kw in text_lower) + (2 if patent_number_match or application_number_match else 0)

    if design_number_match:
        return {"ip_type": "DESIGN_REGISTRATION", "confidence": min(0.9 + design_score * 0.03, 0.99)}
    if patent_number_match or application_number_match:
        return {"ip_type": "PATENT", "confidence": min(0.9 + patent_score * 0.03, 0.99)}
    if design_score > patent_score and design_score >= 2:
        return {"ip_type": "DESIGN_REGISTRATION", "confidence": min(0.7 + design_score * 0.05, 0.95)}
    if patent_score > design_score and patent_score >= 2:
        return {"ip_type": "PATENT", "confidence": min(0.7 + patent_score * 0.05, 0.95)}
    if patent_score > 0:
        return {"ip_type": "PATENT", "confidence": min(0.6 + patent_score * 0.05, 0.85)}
    if design_score > 0:
        return {"ip_type": "DESIGN_REGISTRATION", "confidence": min(0.6 + design_score * 0.05, 0.85)}
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


def _ocr_preprocess_variants(image_bytes: bytes) -> list[bytes]:
    """Deterministic, free preprocessing variants for scanned-image OCR.

    Embedded-text PDFs bypass this entirely (process_document fast path).
    For true scans we try: original, grayscale+contrast, thresholded, upscaled.
    All variants are closed deterministically; failures fall back to original.
    """
    variants: list[bytes] = [image_bytes]
    try:
        from PIL import Image, ImageEnhance, ImageOps
        import io as _io

        # Load once
        try:
            img = Image.open(_io.BytesIO(image_bytes))
        except Exception:
            return variants

        # Grayscale + autocontrast + slight contrast boost
        try:
            gray = img.convert("L")
            # Autocontrast normalizes brightness range
            try:
                gray = ImageOps.autocontrast(gray, cutoff=1)
            except Exception:
                pass
            # Contrast enhance 1.4x
            try:
                enhancer = ImageEnhance.Contrast(gray)
                gray = enhancer.enhance(1.4)
            except Exception:
                pass
            # Convert back to RGB for engines that expect RGB
            if gray.mode != "RGB":
                gray_rgb = gray.convert("RGB")
            else:
                gray_rgb = gray
            buf = _io.BytesIO()
            gray_rgb.save(buf, format="PNG")
            variants.append(buf.getvalue())
        except Exception:
            pass

        # Thresholded variant via OpenCV Otsu (if available)
        try:
            cv2 = _safe_import("cv2")
            if cv2 is not None:
                import numpy as _np

                # Use grayscale variant if we created it, else original
                pil_for_thresh = gray if "gray" in locals() else img.convert("L")
                arr = _np.array(pil_for_thresh)
                # Otsu threshold
                _, thresh = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                # Back to PIL
                thresh_pil = Image.fromarray(thresh)
                # Ensure RGB
                if thresh_pil.mode != "RGB":
                    thresh_pil = thresh_pil.convert("RGB")
                buf2 = _io.BytesIO()
                thresh_pil.save(buf2, format="PNG")
                variants.append(buf2.getvalue())
        except Exception:
            pass

        # Upscaled 2x for small/low-res scans (deterministic, no interpolation artifacts for OCR)
        try:
            w, h = img.size
            if max(w, h) < 1200:
                up = img.resize((w * 2, h * 2), Image.LANCZOS if hasattr(Image, "LANCZOS") else Image.BICUBIC)
                buf3 = _io.BytesIO()
                # Preserve mode
                up.save(buf3, format="PNG")
                variants.append(buf3.getvalue())
        except Exception:
            pass

        # Deduplicate by bytes length/content hash to avoid redundant OCR
        seen = set()
        deduped: list[bytes] = []
        for v in variants:
            h = hash(v)
            if h not in seen:
                seen.add(h)
                deduped.append(v)
        return deduped if deduped else [image_bytes]
    except Exception:
        return [image_bytes]


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
    # Try deterministic preprocessing variants before falling back to external OCR.Space
    variants = _ocr_preprocess_variants(image_bytes)
    for idx, variant in enumerate(variants):
        for engine in (_ocr_with_paddle, _ocr_with_tesseract):
            result = engine(variant, page_number)
            local_warnings.extend(result.warnings)
            if result.text.strip():
                if idx > 0:
                    result.warnings = list(result.warnings) + [f"OCR succeeded on preprocessed variant {idx}"]
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
    raw_payloads: list[str] = []  # includes empty/invalid for diagnostics
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
            return QRResult(success=False, qr_data=[], source="unavailable", warnings=warnings + [f"Image decode failed: {inner_exc}"], evidence=[])

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

    if not image_sources:
        return QRResult(success=False, qr_data=[], source="unavailable", warnings=["No image sources for QR decode"], evidence=[])

    # Collect across all pages/variants without early exit — preserves multiple QRs
    detected_source = "none"
    for label, candidate in image_sources:
        # Deterministic variants: original + rotated + upscaled (for low-quality)
        variants = _prepare_qr_variants(candidate)
        for vlabel, variant in variants:
            full_label = f"{label}:{vlabel}" if vlabel != "original" else label
            # pyzbar primary
            if pyzbar is not None:
                try:
                    decoded = pyzbar.decode(variant)
                    for item in decoded:
                        try:
                            payload = item.data.decode("utf-8", errors="replace").strip()
                        except Exception:
                            payload = ""
                        raw_payloads.append(payload)
                        is_valid, _ = _validate_qr_payload(payload)
                        # Track even empty for diagnostics
                        if payload and payload not in payloads and is_valid:
                            payloads.append(payload)
                            evidence.append(
                                {
                                    "source": full_label,
                                    "type": getattr(item, "type", "QRCODE"),
                                    "payload": payload,
                                    "is_valid": True,
                                    "is_ip_india": _is_ip_india_url(payload),
                                    "is_url": _is_valid_url(payload),
                                }
                            )
                            if detected_source == "none":
                                detected_source = "pyzbar"
                        elif payload == "" and payload not in payloads:
                            # empty payload — record as invalid but keep evidence
                            evidence.append(
                                {
                                    "source": full_label,
                                    "type": getattr(item, "type", "QRCODE"),
                                    "payload": payload,
                                    "is_valid": False,
                                    "reason": "empty payload",
                                }
                            )
                except Exception as exc:
                    warnings.append(f"QR decode skipped for {full_label}: {exc}")

            # OpenCV fallback per variant — requires numpy array, not PIL
            if cv2 is not None:
                try:
                    import numpy as _np

                    # Convert PIL Image → numpy (RGB → BGR for OpenCV)
                    try:
                        if hasattr(variant, "convert"):
                            _pil_for_cv = variant.convert("RGB")
                            _np_img = _np.array(_pil_for_cv)
                            _np_img = cv2.cvtColor(_np_img, cv2.COLOR_RGB2BGR)
                        else:
                            _np_img = _np.array(variant)
                    except Exception as conv_exc:
                        warnings.append(f"OpenCV PIL→numpy conversion failed for {full_label}: {conv_exc}")
                        _np_img = None

                    if _np_img is not None:
                        detector = cv2.QRCodeDetector()
                        # Use detectAndDecodeMulti when available for multiple QRs per variant
                        data = None
                        try:
                            # Newer OpenCV supports detectAndDecodeMulti — handle varying return signatures
                            result_multi = detector.detectAndDecodeMulti(_np_img)
                            # Normalize to (retval, decoded_info)
                            retval_multi = False
                            decoded_info_multi = None
                            if isinstance(result_multi, tuple):
                                if len(result_multi) == 4:
                                    retval_multi, decoded_info_multi, _, _ = result_multi
                                elif len(result_multi) == 3:
                                    retval_multi, decoded_info_multi, _ = result_multi
                                elif len(result_multi) == 2:
                                    retval_multi, decoded_info_multi = result_multi
                                elif len(result_multi) == 1:
                                    retval_multi = bool(result_multi[0])
                                else:
                                    retval_multi = False
                            elif isinstance(result_multi, bool):
                                retval_multi = result_multi
                            if retval_multi and decoded_info_multi is not None:
                                # decoded_info may be tuple/list of strings
                                try:
                                    iterable = decoded_info_multi if isinstance(decoded_info_multi, (list, tuple)) else [decoded_info_multi]
                                except Exception:
                                    iterable = []
                                for d in iterable:
                                    if d:
                                        d = d.strip()
                                        raw_payloads.append(d)
                                        is_valid, _ = _validate_qr_payload(d)
                                        if d and d not in payloads and is_valid:
                                            payloads.append(d)
                                            evidence.append(
                                                {
                                                    "source": full_label,
                                                    "type": "QRCodeDetector",
                                                    "payload": d,
                                                    "is_valid": True,
                                                    "is_ip_india": _is_ip_india_url(d),
                                                    "is_url": _is_valid_url(d),
                                                }
                                            )
                                            if detected_source == "none":
                                                detected_source = "opencv"
                                        elif d == "":
                                            evidence.append({"source": full_label, "type": "QRCodeDetector", "payload": d, "is_valid": False, "reason": "empty payload"})
                                # If multi returned something, skip single
                                if payloads:
                                    continue
                        except (AttributeError, ValueError, TypeError) as e:
                            # No QR or API mismatch — not a warning, just continue to single
                            pass
                        # Single QR fallback — handle varying return signatures
                        try:
                            result_single = detector.detectAndDecode(_np_img)
                            if isinstance(result_single, tuple):
                                if len(result_single) == 3:
                                    data, _, _ = result_single
                                elif len(result_single) == 2:
                                    data, _ = result_single
                                elif len(result_single) == 1:
                                    data = result_single[0]
                                else:
                                    data = None
                            else:
                                data = result_single
                        except Exception as e:
                            warnings.append(f"OpenCV QR detector failed for {full_label}: {e}")
                            data = None
                    if data is not None:
                        data = data.strip()
                        raw_payloads.append(data)
                        is_valid, _ = _validate_qr_payload(data)
                        if data and data not in payloads and is_valid:
                            payloads.append(data)
                            evidence.append(
                                {
                                    "source": full_label,
                                    "type": "QRCodeDetector",
                                    "payload": data,
                                    "is_valid": True,
                                    "is_ip_india": _is_ip_india_url(data),
                                    "is_url": _is_valid_url(data),
                                }
                            )
                            if detected_source == "none":
                                detected_source = "opencv"
                        elif data == "":
                            # Empty decode — still evidence but not valid
                            # Avoid duplicate empty evidence
                            if not any(e.get("payload") == "" and e.get("source") == full_label for e in evidence):
                                evidence.append({"source": full_label, "type": "QRCodeDetector", "payload": data, "is_valid": False, "reason": "empty payload"})
                except Exception as exc:
                    warnings.append(f"OpenCV QR detector failed for {full_label}: {exc}")

    # Post-collection validation and source distinction
    if payloads:
        # Preserve all valid payloads; do not lose multiple
        return QRResult(success=True, qr_data=list(payloads), source=detected_source, warnings=warnings, evidence=evidence)

    # No valid payloads — distinguish unavailable vs detected-but-invalid vs empty
    if raw_payloads:
        # At least one decode attempt produced a payload (even if empty/invalid)
        has_empty = any(p == "" for p in raw_payloads)
        has_invalid = any(p and not _validate_qr_payload(p)[0] for p in raw_payloads)
        if has_empty:
            warnings.append("QR detected but payload empty/invalid")
            return QRResult(success=False, qr_data=[], source="invalid", warnings=warnings, evidence=evidence)
        if has_invalid:
            warnings.append("QR detected but payload invalid")
            return QRResult(success=False, qr_data=[], source="invalid", warnings=warnings, evidence=evidence)

    # Truly no QR
    if not warnings:
        warnings.append("No QR code detected")
    return QRResult(success=False, qr_data=[], source="none", warnings=warnings, evidence=evidence)

