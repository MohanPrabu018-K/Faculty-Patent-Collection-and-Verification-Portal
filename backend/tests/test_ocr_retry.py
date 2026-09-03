"""Focused tests for OCR.Space retry / backoff behaviour (no network)."""
from __future__ import annotations

import httpx
import pytest
from app.core.config import ocr_space_settings
from app.services import ocr_pipeline


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)

    def json(self):
        return self._payload


_OK_PAYLOAD = {
    "IsErroredOnProcessing": False,
    "ParsedResults": [{"ParsedText": "HELLO WORLD", "FileParseExitCode": 1}],
}


@pytest.fixture(autouse=True)
def _fast_settings(monkeypatch):
    monkeypatch.setattr(ocr_space_settings, "api_key", "TEST-KEY", raising=False)
    monkeypatch.setattr(ocr_space_settings, "max_retries", 3, raising=False)
    monkeypatch.setattr(ocr_space_settings, "backoff_seconds", 0.0, raising=False)
    monkeypatch.setattr(ocr_pipeline.time, "sleep", lambda *_: None)


def _patch_post(monkeypatch, responses):
    calls = {"n": 0}

    def fake_post(*args, **kwargs):
        idx = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        item = responses[idx]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


def test_retries_on_429_then_succeeds(monkeypatch):
    calls = _patch_post(monkeypatch, [_FakeResponse(429), _FakeResponse(200, _OK_PAYLOAD)])
    result = ocr_pipeline._ocr_image_bytes(b"img", page_number=1)
    assert result.text == "HELLO WORLD"
    assert calls["n"] == 2


def test_retries_exhausted_on_persistent_429(monkeypatch):
    calls = _patch_post(monkeypatch, [_FakeResponse(429)])
    result = ocr_pipeline._ocr_image_bytes(b"img")
    assert result.text == ""
    assert calls["n"] == 3
    assert any("retries exhausted" in w for w in result.warnings)


def test_retries_on_network_error_then_succeeds(monkeypatch):
    calls = _patch_post(
        monkeypatch,
        [httpx.ConnectError("boom"), _FakeResponse(200, _OK_PAYLOAD)],
    )
    result = ocr_pipeline._ocr_image_bytes(b"img")
    assert result.text == "HELLO WORLD"
    assert calls["n"] == 2


def test_no_retry_on_permanent_error(monkeypatch):
    payload = {
        "IsErroredOnProcessing": True,
        "ErrorMessage": "Invalid API key",
        "ParsedResults": [],
    }
    calls = _patch_post(monkeypatch, [_FakeResponse(200, payload)])
    result = ocr_pipeline._ocr_image_bytes(b"img")
    assert result.text == ""
    assert calls["n"] == 1
    assert any("Invalid API key" in w for w in result.warnings)


def test_success_first_try_single_call(monkeypatch):
    calls = _patch_post(monkeypatch, [_FakeResponse(200, _OK_PAYLOAD)])
    result = ocr_pipeline._ocr_image_bytes(b"img")
    assert result.text == "HELLO WORLD"
    assert calls["n"] == 1


def test_missing_api_key_short_circuits(monkeypatch):
    monkeypatch.setattr(ocr_space_settings, "api_key", "", raising=False)
    calls = _patch_post(monkeypatch, [_FakeResponse(200, _OK_PAYLOAD)])
    result = ocr_pipeline._ocr_image_bytes(b"img")
    assert result.text == ""
    assert calls["n"] == 0
    assert any("not configured" in w for w in result.warnings)
