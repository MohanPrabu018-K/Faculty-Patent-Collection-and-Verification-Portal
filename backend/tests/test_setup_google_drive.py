"""Tests for scripts/setup_google_drive.py.

Validates credential sanitization, JSON client secrets file loading,
pre-flight credential validation logic, and error handling.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import urllib.error

import pytest

import sys

# Ensure repository root is on sys.path so scripts can be imported
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.setup_google_drive import (
    find_downloaded_credentials_files,
    load_credentials_file,
    preflight_verify_credentials,
    sanitize_credential,
)


def test_sanitize_credential_whitespace() -> None:
    assert sanitize_credential("   my_secret   \t\r\n") == "my_secret"
    assert sanitize_credential(None) == ""
    assert sanitize_credential("") == ""


def test_sanitize_credential_quotes() -> None:
    assert sanitize_credential('"GOCSPX-secret123"') == "GOCSPX-secret123"
    assert sanitize_credential("'GOCSPX-secret456'") == "GOCSPX-secret456"
    assert sanitize_credential('  "GOCSPX-secret789"  ') == "GOCSPX-secret789"


def test_sanitize_credential_zero_width_and_bom() -> None:
    assert sanitize_credential("\u200b\ufeffmy_id.apps.googleusercontent.com\u200b") == "my_id.apps.googleusercontent.com"


def test_load_credentials_file_installed(tmp_path: Path) -> None:
    creds_file = tmp_path / "client_secret.json"
    data = {
        "installed": {
            "client_id": "test-client-id.apps.googleusercontent.com",
            "client_secret": "GOCSPX-test-secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    creds_file.write_text(json.dumps(data), encoding="utf-8")

    client_id, client_secret = load_credentials_file(creds_file)
    assert client_id == "test-client-id.apps.googleusercontent.com"
    assert client_secret == "GOCSPX-test-secret"


def test_load_credentials_file_web_and_quotes(tmp_path: Path) -> None:
    creds_file = tmp_path / "client_secret_web.json"
    data = {
        "web": {
            "client_id": ' "test-web-id.apps.googleusercontent.com" ',
            "client_secret": ' "GOCSPX-web-secret" ',
        }
    }
    creds_file.write_text(json.dumps(data), encoding="utf-8")

    client_id, client_secret = load_credentials_file(creds_file)
    assert client_id == "test-web-id.apps.googleusercontent.com"
    assert client_secret == "GOCSPX-web-secret"


def test_load_credentials_file_invalid(tmp_path: Path) -> None:
    creds_file = tmp_path / "bad_creds.json"
    creds_file.write_text(json.dumps({"unknown_section": {}}), encoding="utf-8")

    with pytest.raises(ValueError, match="missing 'installed' or 'web'"):
        load_credentials_file(creds_file)


def test_preflight_verify_credentials_accepted() -> None:
    # Google returning 400 invalid_grant confirms the client_id & client_secret are recognized and valid
    mock_error = urllib.error.HTTPError(
        url="https://oauth2.googleapis.com/token",
        code=400,
        msg="Bad Request",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(b'{"error": "invalid_grant", "error_description": "Malformed auth code."}'),
    )

    with patch("urllib.request.urlopen", side_effect=mock_error):
        is_valid, msg = preflight_verify_credentials("valid_id", "valid_secret")
        assert is_valid is True
        assert "verified successfully" in msg.lower()


def test_preflight_verify_credentials_invalid_secret() -> None:
    mock_error = urllib.error.HTTPError(
        url="https://oauth2.googleapis.com/token",
        code=401,
        msg="Unauthorized",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(b'{"error": "invalid_client", "error_description": "The provided client secret is invalid."}'),
    )

    with patch("urllib.request.urlopen", side_effect=mock_error):
        is_valid, msg = preflight_verify_credentials("valid_id", "invalid_secret")
        assert is_valid is False
        assert "client secret is invalid" in msg.lower()


def test_preflight_verify_credentials_client_not_found() -> None:
    mock_error = urllib.error.HTTPError(
        url="https://oauth2.googleapis.com/token",
        code=401,
        msg="Unauthorized",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(b'{"error": "invalid_client", "error_description": "The OAuth client was not found."}'),
    )

    with patch("urllib.request.urlopen", side_effect=mock_error):
        is_valid, msg = preflight_verify_credentials("nonexistent_id", "some_secret")
        assert is_valid is False
        assert "not found" in msg.lower()
