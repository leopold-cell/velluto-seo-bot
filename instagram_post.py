#!/usr/bin/env python3
"""
Publish a Reel to Instagram via the official Graph API (Content Publishing).

Two-step flow per Meta docs:
  1) POST /{ig_user_id}/media   media_type=REELS, video_url=<public URL>, caption=...
     → returns a container id; the video is fetched + transcoded ASYNC by Meta.
  2) poll /{container_id}?fields=status_code until FINISHED (or ERROR/EXPIRED)
  3) POST /{ig_user_id}/media_publish  creation_id=<container id>  → live media id

The video_url MUST be publicly reachable by Meta (Higgsfield's raw URL, or a Google
Drive direct-download link — NOT Shopify, per project constraint).

Env (.env):
  IG_ACCESS_TOKEN   long-lived Page token (from instagram_auth.py)
  IG_USER_ID        Instagram business-account id (from instagram_auth.py)
  IG_AUTOPOST       "1" to actually publish; anything else = dry-run/no-op (TEST MODE)

publish_reel(video_url, caption) -> media_id | "" (never raises; logs + returns "").
"""
from __future__ import annotations

import os
import time

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(BASE, ".env"), override=True)

GRAPH = "https://graph.facebook.com/v21.0"


def _creds():
    return os.getenv("IG_ACCESS_TOKEN", "").strip(), os.getenv("IG_USER_ID", "").strip()


def is_configured() -> bool:
    tok, uid = _creds()
    return bool(tok and uid)


def autopost_enabled() -> bool:
    return os.getenv("IG_AUTOPOST", "").strip() in ("1", "true", "yes", "on")


def _poll_container(container_id: str, token: str, tries: int = 30, delay: int = 6) -> str:
    """Wait until Meta finishes ingesting the video. Returns status_code."""
    for _ in range(tries):
        r = requests.get(f"{GRAPH}/{container_id}", params={
            "fields": "status_code,status", "access_token": token}, timeout=30).json()
        code = (r.get("status_code") or "").upper()
        if code == "FINISHED":
            return code
        if code in ("ERROR", "EXPIRED"):
            print(f"   ⚠️  IG container {code}: {r.get('status')}")
            return code
        time.sleep(delay)
    print("   ⚠️  IG container still processing after poll window")
    return "IN_PROGRESS"


def publish_reel(video_url: str, caption: str = "", share_to_feed: bool = True) -> str:
    """Create a REELS container from a public video URL and publish it. Returns the
    published media id, or "" if not configured / autopost off / any error."""
    token, uid = _creds()
    if not (token and uid):
        print("   ▶ IG post skip — IG_ACCESS_TOKEN / IG_USER_ID not set (run instagram_auth.py)")
        return ""
    if not video_url:
        print("   ▶ IG post skip — no public video_url")
        return ""
    if not autopost_enabled():
        print("   ▶ IG post DRY-RUN (IG_AUTOPOST≠1) — would publish Reel:")
        print(f"     video: {video_url}")
        print(f"     caption: {caption[:80]}…")
        return ""
    try:
        # 1) container
        r = requests.post(f"{GRAPH}/{uid}/media", data={
            "media_type": "REELS", "video_url": video_url, "caption": caption,
            "share_to_feed": "true" if share_to_feed else "false",
            "access_token": token}, timeout=60).json()
        cid = r.get("id")
        if not cid:
            print(f"   ⚠️  IG container create failed: {r}")
            return ""
        print(f"   ✓ IG container {cid} — waiting for Meta to ingest the video…")
        # 2) wait for ingest
        if _poll_container(cid, token) != "FINISHED":
            return ""
        # 3) publish
        pub = requests.post(f"{GRAPH}/{uid}/media_publish", data={
            "creation_id": cid, "access_token": token}, timeout=60).json()
        mid = pub.get("id")
        if not mid:
            print(f"   ⚠️  IG publish failed: {pub}")
            return ""
        print(f"   ✅ Reel published — media id {mid}")
        return mid
    except Exception as e:
        print(f"   ⚠️  IG publish error: {e}")
        return ""


if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else os.getenv("IG_TEST_VIDEO_URL", "")
    cap = sys.argv[2] if len(sys.argv) > 2 else "Test reel via Graph API 🚴"
    print("Configured:", is_configured(), "| Autopost:", autopost_enabled())
    print("Result:", publish_reel(url, cap) or "(no post)")
