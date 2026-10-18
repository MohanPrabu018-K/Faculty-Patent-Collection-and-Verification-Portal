#!/usr/bin/env python3
"""Interactive Google Drive OAuth 2.0 Setup Utility for FPP.

This script helps configure Google Drive document storage for a 100% Free (₹0) personal
Google account (@gmail.com) without requiring a credit card, Cloud Billing, or Google Workspace.

It guides the user through:
1. Creating an OAuth 2.0 Desktop Application Client ID in Google Cloud Console.
2. Authorizing the portal application with the 'https://www.googleapis.com/auth/drive.file' scope.
3. Generating a long-lived Refresh Token.
4. Optionally creating a designated private folder ('Faculty_Patent_Documents') in Google Drive.
5. Emitting the exact configuration variables for .env and the Render Dashboard.

Usage:
    python scripts/setup_google_drive.py
    python scripts/setup_google_drive.py --client-id <ID> --client-secret <SECRET>
"""
from __future__ import annotations

import argparse
import os
import sys

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
except ImportError:
    print(
        "ERROR: Required Google libraries not found. Run:\n"
        "    pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
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
    print("  7. Copy the Client ID and Client Secret.\n")


def main() -> None:
    print_banner()

    parser = argparse.ArgumentParser(description="Generate Google Drive OAuth credentials.")
    parser.add_argument("--client-id", help="Google Cloud OAuth Client ID")
    parser.add_argument("--client-secret", help="Google Cloud OAuth Client Secret")
    args = parser.parse_args()

    client_id = args.client_id or os.environ.get("GOOGLE_DRIVE_CLIENT_ID")
    client_secret = args.client_secret or os.environ.get("GOOGLE_DRIVE_CLIENT_SECRET")

    if not client_id or not client_secret:
        print_instructions()
        client_id = input("Enter your Google Client ID: ").strip()
        client_secret = input("Enter your Google Client Secret: ").strip()

    if not client_id or not client_secret:
        print("\nERROR: Client ID and Client Secret are required.")
        sys.exit(1)

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
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

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
            folder_id = input("Enter existing Google Drive Folder ID: ").strip()

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
