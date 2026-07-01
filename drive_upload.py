#!/usr/bin/env python3
"""
Upload a local file (the captioned Reel) to Google Drive and return a PUBLIC
direct-download URL that Instagram's Graph API can fetch.

Hosting policy for this project: the Reel video is hosted on Higgsfield (raw clip)
or Google Drive (captioned clip) — never Shopify. This module is the Drive path.

Auth — set ONE of these in .env:
  GOOGLE_SERVICE_ACCOUNT_JSON = /path/to/service_account.json
      (upload target must be a Shared-Drive folder the SA can write to; set
       GDRIVE_FOLDER_ID to that folder. Plain "My Drive" gives SAs 0 quota.)
  GOOGLE_OAUTH_TOKEN_JSON     = /path/to/token.json      (user OAuth creds)
Optional:
  GDRIVE_FOLDER_ID = destination folder id

upload_public(local_path) -> direct-download URL | "" (never raises; logs + "").

Returning "" lets the caller fall back to the raw Higgsfield URL, so a missing/
broken Drive setup never blocks posting.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

BASE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(BASE, ".env"), override=True)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def is_configured() -> bool:
    cid    = os.getenv("GOOGLE_DRIVE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID")
    csec   = os.getenv("GOOGLE_DRIVE_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET")
    rtoken = os.getenv("GOOGLE_DRIVE_REFRESH_TOKEN")
    return bool((cid and csec and rtoken) or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
                or os.getenv("GOOGLE_OAUTH_TOKEN_JSON"))


def _service():
    """Build a Drive API client from whichever credential is configured.

    Priority:
      1) OAuth refresh token in env (GOOGLE_CLIENT_ID/SECRET + GOOGLE_DRIVE_REFRESH_TOKEN)
         — preferred: no service-account key needed (orgs often block SA keys), uploads
         run as the real user with normal Drive quota (My Drive or Shared Drive).
      2) Service-account JSON (GOOGLE_SERVICE_ACCOUNT_JSON) — Shared Drive only.
      3) OAuth authorized-user file (GOOGLE_OAUTH_TOKEN_JSON).
    """
    from googleapiclient.discovery import build

    # Drive-specific client overrides fall back to the shared GSC OAuth client, so a
    # separate Desktop client for Drive won't clobber the Search-Console credentials.
    cid    = (os.getenv("GOOGLE_DRIVE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID", "")).strip()
    csec   = (os.getenv("GOOGLE_DRIVE_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET", "")).strip()
    rtoken = os.getenv("GOOGLE_DRIVE_REFRESH_TOKEN", "").strip()
    sa     = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    oauth  = os.getenv("GOOGLE_OAUTH_TOKEN_JSON", "").strip()

    if cid and csec and rtoken:
        from google.oauth2.credentials import Credentials
        creds = Credentials(
            token=None, refresh_token=rtoken, client_id=cid, client_secret=csec,
            token_uri="https://oauth2.googleapis.com/token", scopes=SCOPES)
    elif sa and os.path.isfile(sa):
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(sa, scopes=SCOPES)
    elif oauth and os.path.isfile(oauth):
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file(oauth, SCOPES)
    else:
        return None
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def upload_public(local_path: str, name: str | None = None) -> str:
    """Upload the file, make it link-readable, return a direct-download URL."""
    if not local_path or not os.path.isfile(local_path):
        print(f"   ▶ Drive skip — file not found: {local_path}")
        return ""
    if not is_configured():
        print("   ▶ Drive skip — no credentials in .env. Set GOOGLE_DRIVE_REFRESH_TOKEN "
              "(+ GOOGLE_CLIENT_ID/SECRET), or GOOGLE_SERVICE_ACCOUNT_JSON.")
        return ""
    try:
        from googleapiclient.http import MediaFileUpload
        svc = _service()
        if svc is None:
            print("   ▶ Drive skip — credential file missing/unreadable")
            return ""

        meta = {"name": name or os.path.basename(local_path)}
        folder = os.getenv("GDRIVE_FOLDER_ID", "").strip()
        if folder:
            meta["parents"] = [folder]

        media = MediaFileUpload(local_path, mimetype="video/mp4", resumable=True)
        f = svc.files().create(body=meta, media_body=media, fields="id",
                               supportsAllDrives=True).execute()
        fid = f["id"]

        # Anyone-with-the-link can read → required so Meta can fetch the video.
        svc.permissions().create(fileId=fid, body={"type": "anyone", "role": "reader"},
                                 supportsAllDrives=True).execute()

        url = f"https://drive.google.com/uc?export=download&id={fid}"
        print(f"   ✓ Drive upload → {url}")
        return url
    except Exception as e:
        print(f"   ⚠️  Drive upload failed: {e}")
        return ""


if __name__ == "__main__":
    import sys
    print("Configured:", is_configured())
    if len(sys.argv) > 1:
        print("URL:", upload_public(sys.argv[1]) or "(none)")
