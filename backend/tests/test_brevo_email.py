"""Brevo transactional-email integration tests (mocked HTTP, no real sends).

Covers the task's automated-testing matrix:

CONFIGURATION
- missing API key / missing sender email -> provider unavailable
- valid configuration -> "brevo" (SMTP credentials NOT required)
- SMTP-only configuration still selects "smtp" (fallback preserved)

BREVO API
- correct endpoint, method, headers, sender, recipient, subject, bodies, URL
- success (201 + messageId), invalid key (401), forbidden (403),
  rate-limit (429), server error (500), timeout, network failure,
  malformed success body

PASSWORD RESET (via the real forgot-password route, Brevo transport mocked)
- unconfigured -> 503 EMAIL_UNAVAILABLE, identical for known/unknown emails,
  no token minted, no HTTP attempted
- configured + accepted -> 200 generic message, token minted (hashed)
- configured + provider failure -> 200 generic message, token stays valid
- response bodies never contain the token or the API key

All hermetic: throwaway users + events, created and deleted by fixtures.
``httpx.AsyncClient`` is monkeypatched — no network traffic is possible.
"""
import asyncio
import uuid
from datetime import datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import get_async_session_context
from app.core.security import hash_password, verify_password
from app.main import app
from app.models.base import AuditLog, Notification, SecurityEvent, User
from app.services import transactional_email as tx

GENERIC_MESSAGE = "If the email is registered, a password reset link has been sent."
UNAVAILABLE_MESSAGE = "Password reset email is currently unavailable. Please contact the administrator."


def _clear_rate_limiters():
    """Reset both process-global limiters (same hygiene as
    test_login_enumeration.py).

    forgot-password is throttled per IP via the handler's own
    deps.check_rate_limit (app.api.deps.rate_limit_state). That state is
    process-global and shared by every test file in the run, so without
    clearing it this file's results depend on how many auth requests earlier
    files made (unrelated password-reset tests fail on 429). Clearing is test
    hygiene, not a weakened assertion: the limiter stays fully in force for
    every request these tests make (test_rate_limit_enforced proves it).
    """
    from app.api.deps import rate_limit_state
    from app.core.security_middleware import _rate_limiter

    rate_limit_state.counts.clear()
    if hasattr(_rate_limiter, "_buckets"):
        _rate_limiter._buckets.clear()


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    _clear_rate_limiters()
    yield


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code=201, payload=None, broken_json=False):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"messageId": "<202501010000.00000001@example.brevo.com>"}
        self._broken = broken_json

    def json(self):
        if self._broken:
            raise ValueError("not json")
        return self._payload


class _FakeAsyncClient:
    """Records how it was called; returns the canned response / raises."""
    last_instance = None

    def __init__(self, response=None, exc=None, **kwargs):
        self.kwargs = kwargs
        self.response = response if response is not None else _FakeResponse()
        self.exc = exc
        self.calls = []
        _FakeAsyncClient.last_instance = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "headers": dict(headers or {}), "json": json})
        if self.exc is not None:
            raise self.exc
        return self.response

    async def get(self, url, headers=None):
        self.calls.append({"url": url, "headers": dict(headers or {}), "json": None})
        if self.exc is not None:
            raise self.exc
        return self.response


def _enable_brevo(monkeypatch, sender="mohanprabu018@gmail.com"):
    from app.core.config import brevo_settings, smtp_settings
    monkeypatch.setattr(brevo_settings, "brevo_api_key", "xkeysib-test-key")
    monkeypatch.setattr(brevo_settings, "brevo_sender_email", sender)
    monkeypatch.setattr(brevo_settings, "brevo_sender_name", "Faculty Patent Portal")
    # Prove SMTP credentials are NOT required for the Brevo path.
    monkeypatch.setattr(smtp_settings, "smtp_enabled", False)
    monkeypatch.setattr(smtp_settings, "smtp_host", "")
    monkeypatch.setattr(smtp_settings, "frontend_reset_url", "https://staging.example.test")


def _disable_all_email(monkeypatch):
    from app.core.config import brevo_settings, smtp_settings
    monkeypatch.setattr(brevo_settings, "brevo_api_key", "")
    monkeypatch.setattr(brevo_settings, "brevo_sender_email", "")
    monkeypatch.setattr(smtp_settings, "smtp_enabled", False)
    monkeypatch.setattr(smtp_settings, "smtp_host", "")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def temp_user():
    email = f"brevo.{uuid.uuid4().hex[:10]}@gmail.com"
    uid = str(uuid.uuid4())

    async def _create():
        async with get_async_session_context() as db:
            db.add(User(
                id=uid, email=email, full_name="Brevo Probe",
                password_hash=hash_password("secret123"), role="faculty",
                faculty_id=f"FAC-BREVO-{uuid.uuid4().hex[:6]}",
                is_active=True, status="active",
            ))
            await db.commit()

    async def _delete():
        async with get_async_session_context() as db:
            for a in (await db.execute(select(AuditLog).where(
                    (AuditLog.actor_id == uid) | (AuditLog.entity_id == uid) | (AuditLog.target_id == uid)))).scalars().all():
                await db.delete(a)
            for n in (await db.execute(select(Notification).where(Notification.user_id == uid))).scalars().all():
                await db.delete(n)
            for e in (await db.execute(select(SecurityEvent).where(SecurityEvent.user_id == uid))).scalars().all():
                await db.delete(e)
            u = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
            if u is not None:
                await db.delete(u)
            await db.commit()

    asyncio.run(_create())
    try:
        yield {"id": uid, "email": email}
    finally:
        asyncio.run(_delete())


def _events_for(uid: str):
    async def _q():
        async with get_async_session_context() as db:
            return (await db.execute(select(SecurityEvent).where(SecurityEvent.user_id == uid))).scalars().all()
    return asyncio.run(_q())


# --------------------------------------------------------------------------
# CONFIGURATION
# --------------------------------------------------------------------------

class TestBrevoConfiguration:
    def test_missing_api_key_is_not_configured(self, monkeypatch):
        _disable_all_email(monkeypatch)
        from app.core.config import brevo_settings
        monkeypatch.setattr(brevo_settings, "brevo_sender_email", "mohanprabu018@gmail.com")
        assert tx.active_email_provider() is None
        assert tx.is_email_configured() is False

    def test_missing_sender_is_not_configured(self, monkeypatch):
        _disable_all_email(monkeypatch)
        from app.core.config import brevo_settings
        monkeypatch.setattr(brevo_settings, "brevo_api_key", "xkeysib-test-key")
        assert tx.active_email_provider() is None
        assert tx.is_email_configured() is False

    def test_valid_brevo_needs_no_smtp(self, monkeypatch):
        _enable_brevo(monkeypatch)
        assert tx.active_email_provider() == "brevo"
        assert tx.is_email_configured() is True

    def test_brevo_takes_precedence_over_smtp(self, monkeypatch):
        _enable_brevo(monkeypatch)
        from app.core.config import smtp_settings
        monkeypatch.setattr(smtp_settings, "smtp_enabled", True)
        monkeypatch.setattr(smtp_settings, "smtp_host", "smtp.example.test")
        assert tx.active_email_provider() == "brevo"

    def test_smtp_fallback_when_brevo_absent(self, monkeypatch):
        _disable_all_email(monkeypatch)
        from app.core.config import smtp_settings
        monkeypatch.setattr(smtp_settings, "smtp_enabled", True)
        monkeypatch.setattr(smtp_settings, "smtp_host", "smtp.example.test")
        assert tx.active_email_provider() == "smtp"
        assert tx.is_email_configured() is True


# --------------------------------------------------------------------------
# BREVO API CONTRACT (mocked transport)
# --------------------------------------------------------------------------

class TestBrevoApiContract:
    def test_request_shape(self, monkeypatch):
        _enable_brevo(monkeypatch)
        monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
        result = asyncio.run(tx.send_reset_via_brevo("mohanprabu1823@gmail.com", "tok-abc-123", "Mohan Prabu"))
        assert result.accepted and result.status == "ACCEPTED"

        inst = _FakeAsyncClient.last_instance
        assert len(inst.calls) == 1
        call = inst.calls[0]
        assert call["url"] == "https://api.brevo.com/v3/smtp/email"
        headers = {k.lower(): v for k, v in call["headers"].items()}
        assert headers["accept"] == "application/json"
        assert headers["content-type"] == "application/json"
        assert headers["api-key"] == "xkeysib-test-key"

        body = call["json"]
        assert body["sender"] == {"name": "Faculty Patent Portal", "email": "mohanprabu018@gmail.com"}
        assert body["to"] == [{"email": "mohanprabu1823@gmail.com"}]
        assert body["subject"] == "Reset Your Password - Faculty Patent Portal"
        assert "https://staging.example.test/reset?token=tok-abc-123" in body["htmlContent"]
        assert "https://staging.example.test/reset?token=tok-abc-123" in body["textContent"]
        assert "Mohan Prabu" in body["htmlContent"]

    def test_success_returns_message_id(self, monkeypatch):
        _enable_brevo(monkeypatch)
        monkeypatch.setattr(httpx, "AsyncClient",
                            lambda **kw: _FakeAsyncClient(response=_FakeResponse(201, {"messageId": "abc123"}), **kw))
        result = asyncio.run(tx.send_reset_via_brevo("a@b.test", "t", "N"))
        assert result.status == "ACCEPTED" and result.http_status == 201 and result.message_id == "abc123"

    @pytest.mark.parametrize("code", [400, 401, 403, 422])
    def test_client_errors_are_rejected(self, monkeypatch, code):
        _enable_brevo(monkeypatch)
        monkeypatch.setattr(httpx, "AsyncClient",
                            lambda **kw: _FakeAsyncClient(response=_FakeResponse(code, {"message": "nope"}), **kw))
        result = asyncio.run(tx.send_reset_via_brevo("a@b.test", "t", "N"))
        assert result.accepted is False and result.status == "REJECTED" and result.http_status == code

    def test_rate_limit(self, monkeypatch):
        _enable_brevo(monkeypatch)
        monkeypatch.setattr(httpx, "AsyncClient",
                            lambda **kw: _FakeAsyncClient(response=_FakeResponse(429, {}), **kw))
        result = asyncio.run(tx.send_reset_via_brevo("a@b.test", "t", "N"))
        assert result.status == "RATE_LIMITED" and result.http_status == 429

    def test_server_error(self, monkeypatch):
        _enable_brevo(monkeypatch)
        monkeypatch.setattr(httpx, "AsyncClient",
                            lambda **kw: _FakeAsyncClient(response=_FakeResponse(500, {}), **kw))
        result = asyncio.run(tx.send_reset_via_brevo("a@b.test", "t", "N"))
        assert result.accepted is False and result.status == "PROVIDER_ERROR"

    def test_timeout_is_provider_error(self, monkeypatch):
        _enable_brevo(monkeypatch)
        timeout_exc = httpx.ConnectTimeout("timed out", request=None)
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(exc=timeout_exc, **kw))
        result = asyncio.run(tx.send_reset_via_brevo("a@b.test", "t", "N"))
        assert result.accepted is False and result.status == "PROVIDER_ERROR" and result.reason == "timeout"

    def test_network_failure_is_provider_error(self, monkeypatch):
        _enable_brevo(monkeypatch)
        monkeypatch.setattr(httpx, "AsyncClient",
                            lambda **kw: _FakeAsyncClient(exc=httpx.ConnectError("down", request=None), **kw))
        result = asyncio.run(tx.send_reset_via_brevo("a@b.test", "t", "N"))
        assert result.accepted is False and result.status == "PROVIDER_ERROR"

    def test_malformed_success_body_still_accepted(self, monkeypatch):
        _enable_brevo(monkeypatch)
        monkeypatch.setattr(httpx, "AsyncClient",
                            lambda **kw: _FakeAsyncClient(response=_FakeResponse(201, broken_json=True), **kw))
        result = asyncio.run(tx.send_reset_via_brevo("a@b.test", "t", "N"))
        assert result.accepted is True and result.status == "ACCEPTED" and result.message_id is None

    def test_unconfigured_short_circuits_without_http(self, monkeypatch):
        _disable_all_email(monkeypatch)

        def _boom(*args, **kwargs):
            raise AssertionError("no HTTP when unconfigured")

        monkeypatch.setattr(httpx, "AsyncClient", _boom)
        result = asyncio.run(tx.send_reset_via_brevo("a@b.test", "t", "N"))
        assert result.status == "NOT_CONFIGURED" and result.accepted is False


# --------------------------------------------------------------------------
# PASSWORD RESET THROUGH THE REAL ROUTE (Brevo transport mocked)
# --------------------------------------------------------------------------

class TestForgotPasswordViaBrevo:
    def test_unconfigured_returns_honest_503_for_any_email(self, client, temp_user, monkeypatch):
        _disable_all_email(monkeypatch)

        def _boom(*args, **kwargs):
            raise AssertionError("no HTTP when unconfigured")

        monkeypatch.setattr(httpx, "AsyncClient", _boom)
        for email in (temp_user["email"], f"nobody.{uuid.uuid4().hex[:8]}@gmail.com"):
            r = client.post("/api/v1/auth/forgot-password", json={"email": email})
            assert r.status_code == 503, r.text
            assert r.json()["error"] == "EMAIL_UNAVAILABLE"
            assert r.json()["message"] == UNAVAILABLE_MESSAGE
        assert _events_for(temp_user["id"]) == []

    def test_accepted_returns_generic_success_and_mints_token(self, client, temp_user, monkeypatch):
        _enable_brevo(monkeypatch)
        monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
        r = client.post("/api/v1/auth/forgot-password", json={"email": temp_user["email"]})
        assert r.status_code == 200, r.text
        assert r.json() == {"message": GENERIC_MESSAGE}
        events = _events_for(temp_user["id"])
        assert len(events) == 1
        assert (events[0].details or {}).get("used") is False

        # The payload actually went to the right recipient with a reset URL.
        inst = _FakeAsyncClient.last_instance
        sent = inst.calls[0]["json"]
        assert sent["to"] == [{"email": temp_user["email"]}]
        assert "/reset?token=" in sent["htmlContent"]

    def test_unknown_email_returns_identical_200(self, client, monkeypatch):
        _enable_brevo(monkeypatch)
        monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
        r = client.post("/api/v1/auth/forgot-password", json={"email": f"nobody.{uuid.uuid4().hex[:8]}@gmail.com"})
        assert r.status_code == 200, r.text
        assert r.json() == {"message": GENERIC_MESSAGE}

    def test_provider_failure_keeps_generic_response_with_valid_token(self, client, temp_user, monkeypatch):
        _enable_brevo(monkeypatch)
        monkeypatch.setattr(httpx, "AsyncClient",
                            lambda **kw: _FakeAsyncClient(response=_FakeResponse(500, {}), **kw))
        r = client.post("/api/v1/auth/forgot-password", json={"email": temp_user["email"]})
        assert r.status_code == 200, r.text
        assert r.json() == {"message": GENERIC_MESSAGE}
        events = _events_for(temp_user["id"])
        assert len(events) == 1
        assert (events[0].details or {}).get("used") is False

    def test_no_token_or_key_leaks_in_responses(self, client, temp_user, monkeypatch):
        _enable_brevo(monkeypatch)
        monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
        r = client.post("/api/v1/auth/forgot-password", json={"email": temp_user["email"]})
        assert r.status_code == 200, r.text
        assert "xkeysib-test-key" not in r.text
        assert "/reset?token=" not in r.text

        sent = _FakeAsyncClient.last_instance.calls[0]["json"]
        assert "xkeysib-test-key" not in str(sent)
        # The emailed token verifies against the stored hash (linkage proof).
        import re
        m = re.search(r"/reset\?token=([A-Za-z0-9_\-]+)", sent["htmlContent"])
        assert m, "reset link must carry the token"
        emailed_token = m.group(1)
        assert len(emailed_token) >= 32

        async def _check():
            async with get_async_session_context() as db:
                events = (await db.execute(
                    select(SecurityEvent).where(SecurityEvent.user_id == temp_user["id"])
                )).scalars().all()
                assert len(events) == 1
                assert verify_password(emailed_token, (events[0].details or {})["token_hash"])

        asyncio.run(_check())

    def test_full_reset_cycle_after_brevo_request(self, client, temp_user, monkeypatch):
        """End-to-end at the API level: Brevo-accepted request -> emailed token
        resets the password -> new password logs in, old one does not."""
        import re

        _enable_brevo(monkeypatch)
        monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
        r = client.post("/api/v1/auth/forgot-password", json={"email": temp_user["email"]})
        assert r.status_code == 200, r.text
        sent = _FakeAsyncClient.last_instance.calls[0]["json"]
        token = re.search(r"/reset\?token=([A-Za-z0-9_\-]+)", sent["htmlContent"]).group(1)

        reset = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "brevo-new-9"})
        assert reset.status_code == 200, reset.text
        assert token not in reset.text
        ok = client.post("/api/v1/auth/login", json={"email": temp_user["email"], "password": "brevo-new-9"})
        assert ok.status_code == 200, ok.text
        reuse = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "another-9"})
        assert reuse.status_code == 401, reuse.text

    def test_rate_limit_enforced(self, client, monkeypatch):
        """Abuse throttle still applies on the Brevo path (regression)."""
        import os

        _enable_brevo(monkeypatch)
        monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
        from app.api import deps as _deps
        from app.core import security_middleware as _sm

        _deps.rate_limit_state.counts.clear()
        if hasattr(_sm._rate_limiter, "_buckets"):
            _sm._rate_limiter._buckets.clear()
        old_e2e, old_env = os.environ.get("E2E_TEST"), os.environ.get("APP_ENV")
        os.environ.pop("E2E_TEST", None)
        os.environ["APP_ENV"] = "test-noe2e"
        try:
            from app.core.config import rate_limit_settings
            limit = rate_limit_settings.login_per_ip
            codes = set()
            # NOTE: must be an address EmailStr accepts (reserved TLDs such
            # as .test/.local are 422 before the handler — and its rate
            # limiter — ever runs).
            probe = f"rl.probe.{uuid.uuid4().hex[:8]}@example.com"
            for _ in range(limit + 3):
                rr = client.post("/api/v1/auth/forgot-password", json={"email": probe})
                codes.add(rr.status_code)
            assert 429 in codes, f"expected a 429 within {limit + 3} calls, got {codes}"
        finally:
            if old_e2e is not None:
                os.environ["E2E_TEST"] = old_e2e
            if old_env is not None:
                os.environ["APP_ENV"] = old_env
            else:
                os.environ.pop("APP_ENV", None)
            _deps.rate_limit_state.counts.clear()
            if hasattr(_sm._rate_limiter, "_buckets"):
                _sm._rate_limiter._buckets.clear()


class TestSenderProbe:
    def test_sender_probe_accepts_list(self, monkeypatch):
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(
            response=_FakeResponse(200, {"senders": [{"email": "mohanprabu018@gmail.com"}]}), **kw))
        result = asyncio.run(tx.check_brevo_sender_status("xkeysib-test-key"))
        assert result.accepted and result.message_id == "mohanprabu018@gmail.com"

    def test_sender_probe_rejects_bad_key(self, monkeypatch):
        monkeypatch.setattr(httpx, "AsyncClient",
                            lambda **kw: _FakeAsyncClient(response=_FakeResponse(401, {}), **kw))
        result = asyncio.run(tx.check_brevo_sender_status("bad-key"))
        assert result.accepted is False and result.status == "REJECTED"
