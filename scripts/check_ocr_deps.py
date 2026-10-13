"""Safe local OCR dependency check — probe only, never processes documents.

Verifies that the app's guaranteed-local OCR engine (Tesseract) is installed
and reachable the same way ``backend/app/services/ocr_pipeline.py`` resolves it:

    TESSERACT_CMD env  ->  PATH  ->  common install directories.

It runs ``tesseract --version`` and, when pytesseract is importable (backend
venv), confirms pytesseract can locate the binary. No document is opened, no
network call is made, and nothing is written.

Usage (from repo root, ideally with the backend venv):

    & backend\\.venv\\Scripts\\python.exe scripts/check_ocr_deps.py

Exit codes: 0 = local OCR available; 1 = Tesseract missing (instructions
printed); 2 = usage error.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

COMMON_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/opt/homebrew/bin/tesseract",
)


def resolve_tesseract() -> str | None:
    candidates: list[str] = []
    env_cmd = os.environ.get("TESSERACT_CMD", "").strip()
    if env_cmd:
        candidates.append(env_cmd)
    which = shutil.which("tesseract")
    if which:
        candidates.append(which)
    candidates.extend(COMMON_PATHS)
    return next((p for p in candidates if p and Path(p).is_file()), None)


def main() -> int:
    cmd = resolve_tesseract()
    if not cmd:
        print("RESULT: FAIL — Tesseract was not found.")
        print("  Tried: TESSERACT_CMD, PATH (`tesseract`), and the common install dirs.")
        print("  Setup options (pick one):")
        print("    Windows:  winget install UB-Mannheim.TesseractOCR  (or set TESSERACT_CMD)")
        print("    Debian:   sudo apt-get install -y tesseract-ocr tesseract-ocr-eng")
        print("    macOS:    brew install tesseract")
        print("  Then re-run this check. See docs/DEPLOYMENT.md 'OCR' section.")
        return 1

    print(f"PATH:  {cmd}")
    try:
        out = subprocess.run(
            [cmd, "--version"], capture_output=True, text=True, timeout=30, check=False
        )
        version_line = (out.stdout or out.stderr or "").splitlines()[0] if (out.stdout or out.stderr) else "(no output)"
        print(f"VERSION: {version_line}")
    except Exception as exc:  # pragma: no cover - OS-level failure
        print(f"VERSION: could not execute tesseract: {exc}")
        return 1

    try:
        import pytesseract  # noqa: F401
    except ImportError:
        print("PYTESSERACT: not importable in this interpreter.")
        print("  For a full pipeline check, run this script with the backend venv:")
        print("    & backend\\.venv\\Scripts\\python.exe scripts/check_ocr_deps.py")
        print("RESULT: PARTIAL — Tesseract binary present; pytesseract not in this interpreter.")
        return 0

    try:
        pytesseract.pytesseract.tesseract_cmd = cmd
        v = pytesseract.get_tesseract_version()
        print(f"PYTESSERACT: OK (invokes {v})")
    except Exception as exc:  # pragma: no cover - binary/language issue
        print(f"PYTESSERACT: FAILED to invoke Tesseract: {exc}")
        return 1

    print("RESULT: OK — local OCR (Tesseract) is available for the backend pipeline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())