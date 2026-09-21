import secrets
import string
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import upload_settings

# Single hasher instance shared by hash/verify so parameters always match.
_password_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=65536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
)


def hash_password(plain_text: str) -> str:
    """Hash a password using Argon2id.

    Returns the hash string suitable for storage.
    """
    return _password_hasher.hash(plain_text)


# Alphabet for generated temporary passwords. Excluded characters are the ones
# that are visually ambiguous (0/O, 1/l/I) and characters that are difficult to
# type or that are likely to break shell quoting / URL encoding when copied.
_TEMP_PW_LOWER = string.ascii_lowercase.replace("l", "")
_TEMP_PW_UPPER = string.ascii_uppercase.replace("I", "").replace("O", "")
_TEMP_PW_DIGITS = string.digits.replace("0", "").replace("1", "")
_TEMP_PW_SPECIAL = "@#$%&*+?=_-"
_TEMP_PW_ALPHABET = _TEMP_PW_LOWER + _TEMP_PW_UPPER + _TEMP_PW_DIGITS + _TEMP_PW_SPECIAL


def generate_temporary_password(length: int = 18) -> str:
    """Generate a cryptographically secure temporary password.

    Uses the standard-library ``secrets`` module (never ``random``). Guarantees
    at least one lowercase, one uppercase, one digit and one special character,
    and excludes visually ambiguous characters.
    """
    if length < 4:
        raise ValueError("length must be at least 4")
    chars = [
        secrets.choice(_TEMP_PW_LOWER),
        secrets.choice(_TEMP_PW_UPPER),
        secrets.choice(_TEMP_PW_DIGITS),
        secrets.choice(_TEMP_PW_SPECIAL),
    ]
    chars += [secrets.choice(_TEMP_PW_ALPHABET) for _ in range(length - 4)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def verify_password(plain_text: str, hashed: str) -> bool:
    """Verify a password against its hash using Argon2id."""
    try:
        _password_hasher.verify(hashed, plain_text)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    except Exception:
        return False


def generate_jwt_token(
    subject: str,
    secret: str,
    algorithm: str = "HS256",
    minutes: int = 30,
    email: str = "",
    role: str = "faculty",
    faculty_id: str = "",
    department_id: str = "",
    full_name: str = "",
) -> str:
    """Generate a JWT token."""
    import jwt
    import time

    issued_at = int(time.time())
    expires_at = issued_at + (minutes * 60)
    token = jwt.encode(
        {
            "sub": subject,
            "email": email,
            "role": role,
            "faculty_id": faculty_id,
            "department_id": department_id,
            "full_name": full_name,
            "iat": issued_at,
            "exp": expires_at,
            "jti": secrets.token_urlsafe(16),
        },
        secret,
        algorithm=algorithm,
    )
    return token


def decode_jwt_token(token: str, secret: str, algorithm: str = "HS256") -> dict[str, Any] | None:
    """Decode and validate a JWT token."""
    import jwt

    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
        return payload
    except Exception:
        return None


def generate_csrf_token() -> str:
    """Generate a CSRF token."""
    return secrets.token_urlsafe(32)


def validate_csrf_token(token: str, session_token: str | None = None) -> bool:
    """Validate a CSRF token using the double-submit cookie pattern.

    The token sent in the X-CSRF-Token header must exactly match the
    csrf_token cookie value for the session.
    """
    if not token or not session_token:
        return False
    return secrets.compare_digest(str(token), str(session_token))


def validate_filename(filename: str, allowed_extensions: list[str] | None = None) -> tuple[bool, str | None]:
    """Validate filename for upload."""
    if not filename:
        return False, "Filename is empty"

    safe_name = Path(filename).name
    if safe_name != filename or not safe_name or safe_name in {".", ".."}:
        return False, "Filename contains path traversal characters"

    if len(safe_name) > 255:
        return False, "Filename too long (max 255 characters)"

    allowed = [ext.lower() for ext in (allowed_extensions or upload_settings.allowed_extensions)]
    ext = Path(safe_name).suffix.lower()
    if ext not in allowed:
        return False, f"Invalid file extension: {ext}"

    dangerous_chars = {'<', '>', ':', '"', '|', '?', '*', '\x00'}
    if any(c in safe_name for c in dangerous_chars):
        return False, "Filename contains invalid characters"

    return True, None
