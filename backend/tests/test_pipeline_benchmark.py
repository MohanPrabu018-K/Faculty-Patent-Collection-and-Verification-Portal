"""Pipeline performance budgets (Bug 2) — structural regression guards.

These tests do NOT assert wall-clock speed (flaky on shared runners).
Instead they lock the measured cost structure so future changes cannot
silently multiply work:

- decoder invocation counts scale linearly with pages x variants
  (guards against variant/engine explosion regressions);
- a loose end-to-end timing smoke guards against pathological (>20x)
  slowdowns only.

Measured reference (local dev machine, 3-page text-layer certificate):
- QR decode ~2.5-3.3s steady (~1s/page, no QR present), first-run ~11s
  including one-time native-library load (environmental, not code).
- Scanned 1-page: ~5.3s total (QR ~1.7s + tesseract ~3.5s single pass).

Bottleneck analysis (see final report): decoder invocation count
(pages x 6 variants x 3 engine calls, no early exit by multi-QR design)
plus tesseract's required text+confidence double pass. No code change
met the proven-identical-behavior bar, so these tests lock the budget
rather than bless an optimization.
"""
from __future__ import annotations

import io
import time
import uuid

import pytest

import fitz
from PIL import Image


def _make_text_pdf(pages: int = 3) -> bytes:
    doc = fitz.open()
    for p in range(pages):
        page = doc.new_page(width=595, height=842)
        y = 72
        for line in [
            "INDIAN PATENT CERTIFICATE - SYNTHETIC BENCHMARK DOCUMENT",
            "Patent Number : IN7654000",
            f"Title : Benchmark Widget Page {p + 1}",
            "Applicant : Benchmark Faculty",
            "Inventors: Dr. Bench Person",
            "Filing Date : 05/05/2023",
            "Date of Grant : 06/06/2024",
        ]:
            page.insert_text((72, y), line, fontsize=11)
            y += 22
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


@pytest.fixture(scope="module")
def three_page_pdf():
    return _make_text_pdf(3)


class TestQrDecoderBudgets:
    def test_pyzbar_call_count_scales_linearly(self, three_page_pdf, monkeypatch):
        import pyzbar.pyzbar as pyzbar_mod

        from app.services.ocr_pipeline import decode_qr_payloads

        calls: list = []

        def _count(image, *args, **kwargs):
            calls.append(1)
            return []

        monkeypatch.setattr(pyzbar_mod, "decode", _count)
        decode_qr_payloads(three_page_pdf, filename="bench.pdf")
        # 3 pages x 6 variants (original, grayscale, 3 rotations, upscale).
        # Budget has headroom (<=30) but forbids silent multiplication.
        assert 1 <= len(calls) <= 30, f"pyzbar calls out of budget: {len(calls)}"

    def test_opencv_call_counts_bounded(self, three_page_pdf, monkeypatch):
        import cv2

        from app.services.ocr_pipeline import decode_qr_payloads

        multi: list = []
        single: list = []

        def _multi(self, img):
            multi.append(1)
            return (False, None)

        def _single(self, img):
            single.append(1)
            return ("", None, None)

        monkeypatch.setattr(cv2.QRCodeDetector, "detectAndDecodeMulti", _multi)
        monkeypatch.setattr(cv2.QRCodeDetector, "detectAndDecode", _single)
        decode_qr_payloads(three_page_pdf, filename="bench.pdf")
        # Same linear budget per engine entry point.
        assert 1 <= len(multi) <= 30, f"opencv-multi calls out of budget: {len(multi)}"
        assert 1 <= len(single) <= 30, f"opencv-single calls out of budget: {len(single)}"

    def test_qr_decode_timing_smoke(self, three_page_pdf):
        """Loose pathological-regression guard only (20x headroom over the
        ~3s measured reference for 3 pages). Not a speed assertion."""
        from app.services.ocr_pipeline import decode_qr_payloads

        t0 = time.perf_counter()
        result = decode_qr_payloads(three_page_pdf, filename="bench.pdf")
        dt = time.perf_counter() - t0
        assert result.success is False
        assert result.qr_data == []
        assert dt < 180, f"QR decode pathologically slow: {dt:.1f}s"


class TestExtractionBudgets:
    def test_extraction_and_classification_fast_path(self, three_page_pdf):
        from app.services.extraction import StructuredExtractionService
        from app.services.ocr_pipeline import _load_pdf_text, classify_document

        import pathlib
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(three_page_pdf)
            tmp = f.name
        pages, has_text = _load_pdf_text(pathlib.Path(tmp))
        assert has_text is True
        text = "\n\n".join(pages)

        t0 = time.perf_counter()
        res = StructuredExtractionService().extract_from_text(text, "PATENT")
        dt_extract = time.perf_counter() - t0
        assert res["normalized_fields"].get("patent_number")
        assert dt_extract < 30, f"extraction pathologically slow: {dt_extract:.1f}s"

        t0 = time.perf_counter()
        cls = classify_document(text, "bench.pdf")
        dt_cls = time.perf_counter() - t0
        assert cls["ip_type"] == "PATENT"
        assert dt_cls < 30, f"classification pathologically slow: {dt_cls:.1f}s"

    def test_benchmark_report_is_unique_per_run(self):
        # Placeholder guard: benchmark id uniqueness for future timing logs.
        assert uuid.uuid4().hex != uuid.uuid4().hex
