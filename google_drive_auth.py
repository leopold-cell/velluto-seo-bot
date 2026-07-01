#!/usr/bin/env python3
"""
One-time: mint a Google Drive refresh token for the reel uploader, reusing the
bot's existing OAuth client (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET in .env).

Why OAuth (not a service-account key): the org policy blocks service-account key
creation, and OAuth uploads run as the real user (normal Drive quota, My Drive or
Shared Drive both work).

Run this on a machine WITH A BROWSER (e.g. your Mac), then copy the printed token
to the VPS .env as GOOGLE_DRIVE_REFRESH_TOKEN. It opens a browser, you approve the
Drive permission, and it prints the refresh token. Nothing is posted anywhere.

  pip install google-auth-oauthlib
  python3 google_drive_auth.py

If you can't run a browser locally, use the Google OAuth Playground instead (see
the chat instructions).
"""
import os

from dotenv import load_dotenv

BASE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE, ".env"), override=True)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main():
    cid = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    csec = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if not cid or not csec:
        raise SystemExit("✗ GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET missing in .env")

    from google_auth_oauthlib.flow import InstalledAppFlow
    cfg = {"installed": {
        "client_id": cid, "client_secret": csec,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"]}}
    flow = InstalledAppFlow.from_client_config(cfg, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent",
                                  authorization_prompt_message="Öffne diese URL im Browser:\n{url}")
    print("\n✅ Drive refresh token (in die VPS-.env als GOOGLE_DRIVE_REFRESH_TOKEN):\n")
    print(creds.refresh_token)
    print("\n(.env-Zeile:)")
    print(f"GOOGLE_DRIVE_REFRESH_TOKEN={creds.refresh_token}")


if __name__ == "__main__":
    main()
