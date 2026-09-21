import json
import os
from pathlib import Path
from typing import List

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# APP_ENV values that switch on production safety guards.
_PROD_ENVS = {"production", "prod", "release", "staging"}
# Substrings that mark a value as an insecure development placeholder.
_DEV_SECRET_MARKERS = ("change-me", "changeme", "dev-secret", "dev-jwt", "insecure", "please-change", "example")


def _load_local_env_file() -> None:
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if value.lower() in {"true", "false"}:
            os.environ[key] = value.lower()
        elif key in {"CORS_ORIGINS", "ALLOWED_EXTENSIONS"} and value and not value.startswith("["):
            parts = [part.strip() for part in value.split(",") if part.strip()]
            os.environ[key] = json.dumps(parts)
        else:
            os.environ[key] = value


for env_name in ("DEBUG", "COOKIE_SECURE"):
    value = os.getenv(env_name)
    if isinstance(value, str) and value.strip().lower() in {"release", "prod", "production"}:
        os.environ[env_name] = "false"

_load_local_env_file()


def _normalize_list_env(*names: str) -> None:
    """pydantic-settings JSON-decodes List[str] env vars in its source layer,
    before field validators run, so a bare comma-separated CORS_ORIGINS would
    fail to parse. Convert `a, b` -> `["a","b"]` here for both real env vars and
    values already loaded from .env."""
    for name in names:
        raw = os.environ.get(name)
        if raw is None:
            continue
        text = raw.strip()
        if not text or text.startswith("["):
            continue
        parts = [p.strip() for p in text.split(",") if p.strip()]
        os.environ[name] = json.dumps(parts)


_normalize_list_env("CORS_ORIGINS", "ALLOWED_EXTENSIONS")


class BaseSettingsBase(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, env_nested_delimiter="__", populate_by_name=True)

    app_env: str = Field(default="development", alias="APP_ENV")
    debug: bool = Field(default=False, alias="DEBUG")
    api_prefix: str = Field(default="/api", alias="API_PREFIX")
    cors_origins: List[str] = Field(default=["http://localhost:5173"], alias="CORS_ORIGINS")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value):
        """Accept CORS_ORIGINS as a comma-separated string (env var) or a JSON
        array. `https://a.example, https://b.example` and `["https://a.example"]`
        both work."""
        if value is None or isinstance(value, list):
            return value
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(text)
            return [part.strip() for part in text.split(",") if part.strip()]
        return value


class AppSettings(BaseSettingsBase):
    app_name: str = Field(default="Faculty Patent Collection Portal", alias="APP_NAME")
    secret_key: str = Field(default="", alias="SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_access_token_minutes: int = Field(default=30, alias="JWT_ACCESS_TOKEN_MINUTES")
    jwt_refresh_token_days: int = Field(default=7, alias="JWT_REFRESH_TOKEN_DAYS")
    cookie_secure: bool = Field(default=False, alias="COOKIE_SECURE")
    cookie_samesite: str = Field(default="lax", alias="COOKIE_SAMESITE")

    @field_validator("secret_key")
    @classmethod
    def _validate_secret_key(cls, value: str) -> str:
        if len(value.strip()) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        return value

    @field_validator("jwt_algorithm")
    @classmethod
    def _validate_jwt_algorithm(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"HS256", "HS384", "HS512"}:
            raise ValueError("JWT_ALGORITHM must be one of HS256, HS384, or HS512")
        return normalized

    @field_validator("jwt_access_token_minutes")
    @classmethod
    def _validate_access_token_minutes(cls, value: int) -> int:
        if not 5 <= value <= 1440:
            raise ValueError("JWT_ACCESS_TOKEN_MINUTES must be between 5 and 1440")
        return value

    @field_validator("jwt_refresh_token_days")
    @classmethod
    def _validate_refresh_token_days(cls, value: int) -> int:
        if not 1 <= value <= 30:
            raise ValueError("JWT_REFRESH_TOKEN_DAYS must be between 1 and 30")
        return value

    @field_validator("cookie_samesite")
    @classmethod
    def _validate_cookie_samesite(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"lax", "strict", "none"}:
            raise ValueError("COOKIE_SAMESITE must be lax, strict, or none")
        return normalized

    @model_validator(mode="after")
    def _cookie_samesite_browser_guard(self):
        """Coerce an unusable SameSite=None-without-Secure combo to Lax.

        Browsers reject `Set-Cookie: ...; SameSite=None` without the Secure
        flag, so the access_token cookie would be silently dropped on plain
        HTTP localhost and every subsequent browser request (e.g. /auth/me)
        would 401 even though login returned 200. Production keeps the
        fail-fast guard in `_production_guards`; this only repairs local
        development / test misconfiguration.
        """
        if (
            self.cookie_samesite == "none"
            and not self.cookie_secure
            and (self.app_env or "").strip().lower() not in _PROD_ENVS
        ):
            self.cookie_samesite = "lax"
        return self

    @model_validator(mode="after")
    def _production_guards(self):
        """Fail fast when APP_ENV is a production environment but the security
        configuration still holds development defaults. Never triggers for
        APP_ENV=development / test."""
        if (self.app_env or "").strip().lower() not in _PROD_ENVS:
            return self

        low = (self.secret_key or "").strip().lower()
        if any(marker in low for marker in _DEV_SECRET_MARKERS):
            raise ValueError(
                "SECRET_KEY is a development placeholder. Set a strong random "
                "SECRET_KEY (>=32 chars, e.g. `python -c \"import secrets;print(secrets.token_urlsafe(48))\"`) "
                "for APP_ENV=" + self.app_env + "."
            )
        if not self.cookie_secure:
            raise ValueError("COOKIE_SECURE must be true for APP_ENV=" + self.app_env + " (HTTPS is required in production).")
        if self.cookie_samesite == "none" and not self.cookie_secure:
            raise ValueError("COOKIE_SAMESITE=none requires COOKIE_SECURE=true.")
        if "*" in self.cors_origins:
            raise ValueError("CORS_ORIGINS must not contain '*' for APP_ENV=" + self.app_env + " (credentials are used).")
        non_local = [o for o in self.cors_origins if "localhost" not in o and "127.0.0.1" not in o]
        if not non_local:
            raise ValueError("CORS_ORIGINS must include the deployed frontend origin (https://…) for APP_ENV=" + self.app_env + ".")
        return self


class DatabaseSettings(BaseSettingsBase):
    database_url: str = Field(default="", alias="DATABASE_URL")

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        if not value.startswith(("postgresql://", "postgresql+asyncpg://")):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL")
        return value

    @model_validator(mode="after")
    def _production_db_guard(self):
        if (self.app_env or "").strip().lower() not in _PROD_ENVS:
            return self
        url = self.database_url or ""
        if "change-me" in url or "changeme" in url:
            raise ValueError("DATABASE_URL is a placeholder. Provide the production PostgreSQL connection string.")
        if "@localhost" in url or "@127.0.0.1" in url:
            raise ValueError("DATABASE_URL points at localhost. Provide the hosted production database URL for APP_ENV=" + self.app_env + ".")
        return self


class VerificationSettings(BaseSettingsBase):
    verification_timeout_seconds: int = Field(default=10, alias="VERIFICATION_TIMEOUT_SECONDS")
    verification_retries: int = Field(default=2, alias="VERIFICATION_RETRIES")
    verification_cache_ttl_seconds: int = Field(default=86400, alias="VERIFICATION_CACHE_TTL_SECONDS")
    # Default jurisdiction used when the caller does not specify one. The portal
    # is an Indian institution, so patent/design numbers are looked up against
    # the Indian Patent Office by default.
    default_country: str = Field(default="IN", alias="VERIFICATION_DEFAULT_COUNTRY")
    # --- Indian Patent Office (IPO / InPASS public search) ---
    # There is no official free REST API for the Indian Patent Office. This
    # points at a JSON endpoint that returns a single record for a given
    # patent/design number (either the InPASS public-search backend or a small
    # self-hosted proxy in front of it). Leave the URL blank to keep the
    # adapter disabled -- verification then degrades gracefully to manual.
    ipindia_enabled: bool = Field(default=False, alias="IPINDIA_ENABLED")
    ipindia_search_url: str = Field(default="", alias="IPINDIA_SEARCH_URL")
    ipindia_timeout_seconds: int = Field(default=15, alias="IPINDIA_TIMEOUT_SECONDS")


class OcrSpaceSettings(BaseSettingsBase):
    api_key: str = Field(default="", alias="OCRSPACE_API_KEY")
    api_url: str = Field(default="https://api.ocr.space/parse/image", alias="OCRSPACE_API_URL")
    language: str = Field(default="eng", alias="OCRSPACE_LANGUAGE")
    ocr_engine: str = Field(default="2", alias="OCRSPACE_OCR_ENGINE")
    timeout_seconds: int = Field(default=30, alias="OCRSPACE_TIMEOUT_SECONDS")
    # Retry / backoff for HTTP 429 and transient (5xx / network / throttle) failures.
    max_retries: int = Field(default=3, alias="OCRSPACE_MAX_RETRIES")
    backoff_seconds: float = Field(default=2.0, alias="OCRSPACE_BACKOFF_SECONDS")

    @field_validator("max_retries")
    @classmethod
    def _validate_max_retries(cls, value: int) -> int:
        if not 1 <= value <= 10:
            raise ValueError("OCRSPACE_MAX_RETRIES must be between 1 and 10")
        return value

    @field_validator("backoff_seconds")
    @classmethod
    def _validate_backoff_seconds(cls, value: float) -> float:
        if not 0 <= value <= 30:
            raise ValueError("OCRSPACE_BACKOFF_SECONDS must be between 0 and 30")
        return value


class LocalOcrSettings(BaseSettingsBase):
    """Local, open-source OCR configuration.

    The pipeline is local-first: PyMuPDF embedded text -> PaddleOCR (optional) ->
    Tesseract -> (optional) OCR.Space. Tesseract is the guaranteed-local engine
    for scanned/image documents. OCR.Space is an optional emergency fallback and
    is never required for normal operation.
    """

    tesseract_cmd: str = Field(default="", alias="TESSERACT_CMD")
    tesseract_langs: str = Field(default="eng", alias="TESSERACT_LANGS")
    ocrspace_fallback_enabled: bool = Field(default=True, alias="OCRSPACE_FALLBACK_ENABLED")


class UploadSettings(BaseSettingsBase):
    storage_backend: str = Field(default="local", alias="STORAGE_BACKEND")
    local_storage_root: str = Field(default="./storage", alias="LOCAL_STORAGE_ROOT")
    max_upload_bytes: int = Field(default=20971520, alias="MAX_UPLOAD_BYTES")
    max_pdf_pages: int = Field(default=50, alias="MAX_PDF_PAGES")
    max_image_dimension: int = Field(default=10000, alias="MAX_IMAGE_DIMENSION")
    allowed_extensions: List[str] = Field(default=[".pdf", ".png", ".jpg", ".jpeg"], alias="ALLOWED_EXTENSIONS")
    clamav_host: str = Field(default="", alias="CLAMAV_HOST")

    @field_validator("max_upload_bytes", "max_pdf_pages", "max_image_dimension")
    @classmethod
    def _validate_positive_ints(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Upload settings must be positive integers")
        return value

    @field_validator("allowed_extensions")
    @classmethod
    def _validate_extensions(cls, value: List[str]) -> List[str]:
        normalized = []
        for ext in value:
            ext = ext.strip().lower()
            if not ext.startswith(".") or len(ext) < 2:
                raise ValueError("Allowed extensions must be dot-prefixed file extensions")
            normalized.append(ext)
        if not normalized:
            raise ValueError("At least one allowed file extension is required")
        return normalized


class RateLimitSettings(BaseSettingsBase):
    login_per_ip: int = Field(default=10, alias="RATE_LIMIT_LOGIN_PER_IP")
    login_per_account: int = Field(default=5, alias="RATE_LIMIT_LOGIN_PER_ACCOUNT")
    upload_per_hour: int = Field(default=50, alias="RATE_LIMIT_UPLOAD_PER_HOUR")
    search_per_minute: int = Field(default=30, alias="RATE_LIMIT_SEARCH_PER_MINUTE")
    api_per_minute: int = Field(default=100, alias="RATE_LIMIT_API_PER_MINUTE")
    account_lockout_attempts: int = Field(default=5, alias="ACCOUNT_LOCKOUT_ATTEMPTS")
    account_lockout_seconds: int = Field(default=900, alias="ACCOUNT_LOCKOUT_SECONDS")

    @field_validator("login_per_ip", "login_per_account", "upload_per_hour", "search_per_minute", "api_per_minute", "account_lockout_attempts", "account_lockout_seconds")
    @classmethod
    def _validate_rate_limit_values(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Rate limit settings must be positive")
        return value


class SmtpSettings(BaseSettingsBase):
    """SMTP configuration for transactional email (password reset, etc.)."""
    smtp_enabled: bool = Field(default=False, alias="SMTP_ENABLED")
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str = Field(default="", alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from_email: str = Field(default="noreply@faculty-portal.local", alias="SMTP_FROM_EMAIL")
    smtp_from_name: str = Field(default="Faculty Patent Portal", alias="SMTP_FROM_NAME")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")
    smtp_timeout_seconds: int = Field(default=15, alias="SMTP_TIMEOUT_SECONDS")
    reset_token_expiry_hours: int = Field(default=1, alias="RESET_TOKEN_EXPIRY_HOURS")
    frontend_reset_url: str = Field(default="http://localhost:5173", alias="FRONTEND_RESET_URL")


class SchedulerSettings(BaseSettingsBase):
    """Scheduler configuration for background jobs."""
    enabled: bool = Field(default=True, alias="SCHEDULER_ENABLED")
    reminder_interval_hours: int = Field(default=24, alias="SCHEDULER_REMINDER_INTERVAL_HOURS")
    expiry_check_interval_hours: int = Field(default=24, alias="SCHEDULER_EXPIRY_CHECK_INTERVAL_HOURS")
    reminder_before_expiry_days: int = Field(default=3, alias="SCHEDULER_REMINDER_BEFORE_EXPIRY_DAYS")
    default_expiry_days: int = Field(default=14, alias="SCHEDULER_DEFAULT_EXPIRY_DAYS")

    @field_validator("reminder_interval_hours", "expiry_check_interval_hours", "reminder_before_expiry_days", "default_expiry_days")
    @classmethod
    def _validate_positive_ints(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Scheduler settings must be positive integers")
        return value


app_settings = AppSettings()
database_settings = DatabaseSettings()
verification_settings = VerificationSettings()
ocr_space_settings = OcrSpaceSettings()
local_ocr_settings = LocalOcrSettings()
upload_settings = UploadSettings()
rate_limit_settings = RateLimitSettings()
smtp_settings = SmtpSettings()
scheduler_settings = SchedulerSettings()


def get_settings():
    return {
        "app": app_settings,
        "database": database_settings,
        "verification": verification_settings,
        "ocr_space": ocr_space_settings,
        "local_ocr": local_ocr_settings,
        "upload": upload_settings,
        "rate_limit": rate_limit_settings,
        "smtp": smtp_settings,
    }
