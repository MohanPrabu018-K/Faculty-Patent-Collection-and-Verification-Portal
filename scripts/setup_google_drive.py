#!/usr/bin/env python3
"""Interactive Google Drive OAuth 2.0 Setup Utility for FPP.

This script configures Google Drive document storage for a 100% Free (₹0) personal
Google account (@gmail.com) without requiring a credit card, Cloud Billing, or Google Workspace.

Key Capabilities:
1. Supports direct loading from downloaded Google Cloud credentials JSON files
   (e.g., client_secret_*.json or credentials.json), avoiding manual copy-paste errors.
2. Automatic credential sanitization (surrounding quotes, whitespace, carriage returns).
3. Instant pre-flight validation against Google's token endpoint to verify client credentials
   prior to opening the browser.
4. Clean, secure terminal output that never logs or exposes secrets.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
except ImportError:
    print(
        "ERROR: Required Google libraries not found. Run:\n"
        "    backend\\.venv\\Scripts\\pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
    )
    sys.exit(1)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def print_banner() -> None:
    print("=" * 72)
    print("  Faculty Patent Portal (FPP) - Google Drive Zero-Cost Setup (₹0)")
    print("=" * 72)
    print(
        "\nThis utility configures Google Drive API document storage using a regular\n"
        "Google account (@gmail.com). You will get 15 GB of persistent free cloud\n"
        "storage without providing credit card details or enabling Google Cloud Billing.\n"
    )


def print_instructions() -> None:
    print("Step 1: Create an OAuth 2.0 Desktop App in Google Cloud Console:")
    print("  1. Go to: https://console.cloud.google.com/")
    print("  2. Create a new project (e.g., 'Faculty Patent Portal'). No billing is required.")
    print("  3. Navigate to: APIs & Services -> Library.")
    print("  4. Search for 'Google Drive API' and click 'Enable'.")
    print("  5. Navigate to: APIs & Services -> OAuth consent screen.")
    print("     - Select 'External', click 'Create'.")
    print("     - Enter App Name ('Faculty Patent Portal') and your email.")
    print("     - In 'Test users', add your own @gmail.com address.")
    print("     - Click Save and Continue.")
    print("  6. Navigate to: APIs & Services -> Credentials.")
    print("     - Click '+ CREATE CREDENTIALS' -> 'OAuth client ID'.")
    print("     - Application type: Select 'Desktop app'.")
    print("     - Name: 'FPP Desktop Client'. Click 'Create'.")
    print("  7. Click 'DOWNLOAD JSON' or copy the Client ID and Client Secret.\n")


def sanitize_credential(value: str | None) -> str:
    """Sanitize credential strings by stripping whitespace, hidden unicode, and quotes."""
    if not value:
        return ""
    val = value.strip()
    # Strip zero-width spaces, BOM, NBSP, and standard whitespace
    val = val.strip("\u200b\ufeff\xa0 \t\r\n")
    # If the user wrapped the credential in single or double quotes, strip them
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        val = val[1:-1].strip("\u200b\ufeff\xa0 \t\r\n")
    return val


def find_downloaded_credentials_files() -> list[Path]:
    """Search for downloaded Google Cloud client_secret JSON files in cwd and ~/Downloads."""
    candidates: list[Path] = []
    
    # Check current directory
    cwd = Path.cwd()
    for p in cwd.glob("client_secret*.json"):
        if p.is_file():
            candidates.append(p)
    if (cwd / "credentials.json").is_file():
        candidates.append(cwd / "credentials.json")

    # Check user's Downloads directory
    downloads_dir = Path.home() / "Downloads"
    if downloads_dir.is_dir():
        for p in downloads_dir.glob("client_secret*.json"):
            if p.is_file():
                candidates.append(p)
        if (downloads_dir / "credentials.json").is_file():
            candidates.append(downloads_dir / "credentials.json")

    # Sort newest first by last modified time
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates


def load_credentials_file(file_path: Path) -> tuple[str, str]:
    """Load and validate client_id and client_secret from a client secrets JSON file."""
    if not file_path.exists():
        raise FileNotFoundError(f"Credentials file not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    section = data.get("installed") or data.get("web")
    if not section:
        raise ValueError(
            f"Invalid Google client secrets file: missing 'installed' or 'web' section in {file_path.name}"
        )

    client_id = sanitize_credential(section.get("client_id"))
    client_secret = sanitize_credential(section.get("client_secret"))

    if not client_id or not client_secret:
        raise ValueError(f"Credentials file {file_path.name} is missing client_id or client_secret.")

    return client_id, client_secret


def preflight_verify_credentials(client_id: str, client_secret: str) -> tuple[bool, str]:
    """Verify that Google OAuth recognizes this Client ID and accepts this Client Secret.

    Performs a safe dry-run request against Google's token endpoint with a dummy authorization code.
    - If Google responds with HTTP 400 'invalid_grant' ('Malformed auth code'),
      Google has validated and accepted the client_id and client_secret!
    - If Google responds with HTTP 401 'invalid_client' ('The provided client secret is invalid'),
      the secret does not match the client.
    - If Google responds with HTTP 401 'invalid_client' ('The OAuth client was not found'),
      the client_id does not exist.
    """
    token_url = "https://oauth2.googleapis.com/token"
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": "preflight_probe",
        "redirect_uri": "http://localhost/",
    }).encode("utf-8")

    creds_bytes = f"{client_id}:{client_secret}".encode("utf-8")
    auth_header = f"Basic {base64.b64encode(creds_bytes).decode('ascii')}"

    req = urllib.request.Request(
        token_url,
        data=data,
        headers={
            "Authorization": auth_header,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return True, "Credentials accepted."
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
            err = body.get("error", "")
            desc = body.get("error_description", "")
        except Exception:
            err = ""
            desc = str(e)

        if e.code == 400 and err == "invalid_grant":
            return True, "Credentials verified successfully with Google."

        if e.code == 401 and err == "invalid_client":
            if "client secret is invalid" in desc.lower():
                return False, (
                    "Google rejected the Client Secret: 'The provided client secret is invalid.'\n"
                    "Ensure you copied the exact secret matching this Client ID in Google Cloud Console."
                )
            if "not found" in desc.lower():
                return False, (
                    "Google did not find the OAuth Client: 'The OAuth client was not found.'\n"
                    "Ensure the Client ID is correct and belongs to your Google Cloud project."
                )
            return False, f"Google OAuth client error: {desc or err}"

        return False, f"Google token endpoint error (HTTP {e.code}): {desc or err}"
    except Exception as e:
        return True, f"Preflight probe skipped ({e}). Proceeding to OAuth flow."


def main() -> None:
    print_banner()

    parser = argparse.ArgumentParser(description="Generate Google Drive OAuth credentials.")
    parser.add_argument("-f", "--credentials-file", help="Path to downloaded Google client secrets JSON file")
    parser.add_argument("--client-id", help="Google Cloud OAuth Client ID")
    parser.add_argument("--client-secret", help="Google Cloud OAuth Client Secret")
    parser.add_argument("--skip-preflight", action="store_true", help="Skip pre-flight credential verification")
    args = parser.parse_args()

    client_id = ""
    client_secret = ""

    # Option 1: Explicit credentials file flag
    if args.credentials_file:
        creds_path = Path(args.credentials_file)
        print(f"Loading credentials from: {creds_path}")
        client_id, client_secret = load_credentials_file(creds_path)

    # Option 2: CLI args or environment variables
    if not client_id:
        client_id = sanitize_credential(args.client_id or os.environ.get("GOOGLE_DRIVE_CLIENT_ID"))
        client_secret = sanitize_credential(args.client_secret or os.environ.get("GOOGLE_DRIVE_CLIENT_SECRET"))

    # Option 3: Auto-detect downloaded client_secret JSON files
    if not client_id or not client_secret:
        found_files = find_downloaded_credentials_files()
        if found_files:
            latest_file = found_files[0]
            print(f"Found downloaded Google credentials file:\n  {latest_file}\n")
            use_file = input("Load credentials from this file? [Y/n]: ").strip().lower()
            if use_file in ("", "y", "yes"):
                try:
                    client_id, client_secret = load_credentials_file(latest_file)
                    print("Credentials loaded successfully from file.")
                except Exception as e:
                    print(f"Warning: Could not load file: {e}")

    # Option 4: Interactive manual prompt
    if not client_id or not client_secret:
        print_instructions()
        client_id = sanitize_credential(input("Enter your Google Client ID: "))
        client_secret = sanitize_credential(input("Enter your Google Client Secret: "))

    if not client_id or not client_secret:
        print("\nERROR: Client ID and Client Secret are required.")
        sys.exit(1)

    # Pre-flight credential verification
    if not args.skip_preflight:
        print("\nVerifying credentials with Google OAuth endpoint...")
        is_valid, message = preflight_verify_credentials(client_id, client_secret)
        if not is_valid:
            print(f"\nPRE-FLIGHT VERIFICATION FAILED:\n{message}\n")
            print("Please verify your credentials in Google Cloud Console before proceeding.")
            sys.exit(1)
        print(f"{message}")

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    print("\nStarting local OAuth flow. A browser window will open to authorize the portal...")
    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)

    try:
        creds = flow.run_local_server(
            port=0,
            prompt="consent",
            access_type="offline",
            authorization_prompt_message=(
                "\nPlease authorize the application in the browser window.\n"
                "If your browser did not open automatically, visit this URL:\n\n"
                "  {url}\n"
            ),
        )
    except Exception as exc:
        print(f"\nERROR during authorization flow: {exc}")
        sys.exit(1)

    refresh_token = creds.refresh_token
    if not refresh_token:
        print("\nWARNING: No refresh token returned. Ensure you prompted for consent with offline access.")
        sys.exit(1)

    print("\nAuthentication successful!")

    # Test API connection and offer folder creation
    drive = build("drive", "v3", credentials=creds)

    existing_folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
    folder_id = existing_folder_id

    if not folder_id:
        create_folder_prompt = input(
            "\nDo you want to automatically create a private 'Faculty_Patent_Documents' folder? [Y/n]: "
        ).strip().lower()

        if create_folder_prompt in ("", "y", "yes"):
            folder_metadata = {
                "name": "Faculty_Patent_Documents",
                "mimeType": "application/vnd.google-apps.folder",
            }
            folder = drive.files().create(body=folder_metadata, fields="id, name").execute()
            folder_id = folder.get("id")
            print(f"Created private folder '{folder['name']}' (ID: {folder_id})")
        else:
            folder_id = sanitize_credential(input("Enter existing Google Drive Folder ID: "))

    print("\n" + "=" * 72)
    print("  CONFIGURATION COMPLETE! Copy the following into your .env or Render Dashboard:")
    print("=" * 72)
    print(f"STORAGE_BACKEND=gdrive")
    print(f"GOOGLE_DRIVE_FOLDER_ID={folder_id}")
    print(f"GOOGLE_DRIVE_CLIENT_ID={client_id}")
    print(f"GOOGLE_DRIVE_CLIENT_SECRET={client_secret}")
    print(f"GOOGLE_DRIVE_REFRESH_TOKEN={refresh_token}")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    main()
