"""File-backed runtime overrides for Super Admin editable settings.

Only safe operational values are stored here (upload size). Secrets are never
handled by this module. Persisted to storage/runtime_settings.json.
"""
from __future__ import annotations

import json
from pathlib import Path

_OVERRIDE_FILE = Path(__file__).resolve().parents[3] / "storage" / "runtime_settings.json"

DEFAULT_MAX_UPLOAD_MB = 20.0
MIN_UPLOAD_MB = 1.0
MAX_UPLOAD_MB = 100.0


def _read_overrides() -> dict:
    try:
        if _OVERRIDE_FILE.exists():
            return json.loads(_OVERRIDE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {}


def get_max_upload_bytes(fallback: int) -> int:
    data = _read_overrides()
    try:
        mb = float(data.get("max_upload_mb", fallback / (1024 * 1024)))
    except (TypeError, ValueError):
        return fallback
    if not (MIN_UPLOAD_MB <= mb <= MAX_UPLOAD_MB):
        return fallback
    return int(mb * 1024 * 1024)


def get_max_upload_mb(fallback_bytes: int) -> float:
    return round(get_max_upload_bytes(fallback_bytes) / (1024 * 1024), 1)


def set_max_upload_mb(mb: float) -> float:
    if not (MIN_UPLOAD_MB <= float(mb) <= MAX_UPLOAD_MB):
        raise ValueError(f"max_upload_mb must be between {MIN_UPLOAD_MB} and {MAX_UPLOAD_MB}")
    _OVERRIDE_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = _read_overrides()
    data["max_upload_mb"] = round(float(mb), 1)
    _OVERRIDE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data["max_upload_mb"]
