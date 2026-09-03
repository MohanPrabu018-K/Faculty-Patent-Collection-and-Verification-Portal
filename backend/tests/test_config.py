import pytest
from app.core.config import AppSettings, DatabaseSettings, OcrSpaceSettings, UploadSettings, RateLimitSettings

# Fields whose class defaults these tests assert; a developer's local .env
# (loaded into os.environ at import time) must not leak into the "defaults" check.
_DEFAULTS_ENV_KEYS = ("DEBUG", "APP_ENV", "API_PREFIX", "APP_NAME", "CORS_ORIGINS")


def test_app_settings_defaults(monkeypatch):
    for key in _DEFAULTS_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    settings = AppSettings()
    assert settings.app_name == "Faculty Patent Collection Portal"
    assert settings.debug is False
    assert settings.api_prefix == "/api"
    assert "http://localhost:5173" in settings.cors_origins


def test_database_settings_defaults():
    settings = DatabaseSettings()
    assert "postgresql" in settings.database_url


def test_ocr_space_settings_defaults():
    settings = OcrSpaceSettings()
    assert settings.api_url == "https://api.ocr.space/parse/image"
    assert settings.language == "eng"


def test_upload_settings_defaults():
    settings = UploadSettings()
    assert settings.storage_backend == "local"
    assert settings.max_upload_bytes == 20971520
    assert settings.allowed_extensions == [".pdf", ".png", ".jpg", ".jpeg"]


def test_rate_limit_settings_defaults():
    settings = RateLimitSettings()
    assert settings.login_per_ip == 10
    assert settings.login_per_account == 5
    assert settings.account_lockout_attempts == 5