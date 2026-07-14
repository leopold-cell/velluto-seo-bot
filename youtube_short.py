"""
YouTube Shorts uploader — posts the SAME captioned reel we send to Instagram
to YouTube as a Short (a whole extra search surface: YouTube is search engine
#2, feeds Google video results, and is heavily cited by AI answers).

Uploads the LOCAL captioned mp4 (not a URL — YouTube needs a resumable file
upload). Vertical <60s video with "#Shorts" in the title/description is treated
as a Short automatically.

Auth: reuses the Google OAuth pattern (client id/secret + refresh token) but
with the youtube.upload scope — run youtube_auth.py once to mint it. Set:
  YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET  (or falls back to GOOGLE_CLIENT_ID/SECRET)
  YOUTUBE_REFRESH_TOKEN
  YT_AUTOPOST=1   (arms real posting; otherwise dry-run)

Never raises — logs and returns "" so it can't break the reel pipeline.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
            override=True)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
SITE   = "https://velluto-shop.com"
HASHTAGS = "#Shorts #cycling #roadcycling #cyclingglasses #velluto"
TAGS = ["cycling glasses", "cycling sunglasses", "road cycling", "road bike",
        "cycling eyewear", "velluto", "velluto stradapro", "oakley alternative",
        "fahrradbrille", "wielrenbril", "lunettes vélo"]


def _creds():
    cid    = (os.getenv("YOUTUBE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID", "")).strip()
    csec   = (os.getenv("YOUTUBE_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET", "")).strip()
    rtoken = os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip()
    return cid, csec, rtoken


def is_configured() -> bool:
    cid, csec, rtoken = _creds()
    return bool(cid and csec and rtoken)


def autopost_enabled() -> bool:
    return os.getenv("YT_AUTOPOST", "").strip().lower() in ("1", "true", "yes", "on")


def _service():
    cid, csec, rtoken = _creds()
    if not (cid and csec and rtoken):
        return None
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        creds = Credentials(
            token=None, refresh_token=rtoken, client_id=cid, client_secret=csec,
            token_uri="https://oauth2.googleapis.com/token", scopes=SCOPES)
        return build("youtube", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"   ▶ YouTube: service build failed: {e}")
        return None


def build_metadata(onscreen: str = "", punchline: str = "",
                   caption_line: str = "") -> tuple[str, str, list[str]]:
    """SEO title (<=95 chars, ends with #Shorts), description (hook + soft CTA +
    link + hashtags), tags. Mirrors the IG caption but tuned for YouTube search."""
    hook = (onscreen or caption_line or punchline or "Road cycling POV").strip()
    hook = hook.replace("\n", " ").strip(" .")
    title = hook[:80].rstrip()
    if "velluto" not in title.lower():
        title = f"{title} | Velluto"
    title = f"{title[:86]} #Shorts"
    body_hook = " ".join(x for x in (caption_line or hook, punchline) if x).strip()
    description = (
        f"{body_hook}\n\n"
        f"Velluto StradaPro — 25g ultralight road cycling glasses, interchangeable "
        f"lenses, UV400, anti-fog. From 69 EUR, 30-day risk-free trial.\n"
        f"👉 {SITE}\n\n{HASHTAGS}"
    )
    return title, description, TAGS


def upload_short(video_path: str, title: str, description: str,
                 tags: list[str] | None = None) -> str:
    """Upload a local mp4 as a public YouTube Short. Returns the video id, or ""
    (missing creds / dry-run / file missing / API error — always soft)."""
    if not video_path or not os.path.isfile(video_path):
        print(f"   ▶ YouTube skip — file not found: {video_path}")
        return ""
    if not is_configured():
        print("   ▶ YouTube skip — no creds (set YOUTUBE_REFRESH_TOKEN via youtube_auth.py)")
        return ""
    if not autopost_enabled():
        print(f"   ▶ YouTube DRY-RUN (YT_AUTOPOST≠1) — would upload: {title}")
        return ""
    svc = _service()
    if svc is None:
        return ""
    try:
        from googleapiclient.http import MediaFileUpload
        body = {
            "snippet": {
                "title":       title[:100],
                "description": description[:4900],
                "tags":        (tags or TAGS)[:15],
                "categoryId":  "17",   # Sports
            },
            "status": {
                "privacyStatus":           "public",
                "selfDeclaredMadeForKids": False,
            },
        }
        media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
        req = svc.videos().insert(part="snippet,status", body=body, media_body=media)
        resp = None
        while resp is None:
            _status, resp = req.next_chunk()
        vid = resp.get("id", "")
        if vid:
            print(f"   ✓ YouTube Short published: https://youtu.be/{vid}")
        return vid
    except Exception as e:
        print(f"   ⚠️  YouTube upload failed: {e}")
        return ""


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else os.getenv("YT_TEST_VIDEO", "")
    t, d, tg = build_metadata("Testing the lightest road cycling glasses", "25g. No pressure.")
    print("configured:", is_configured(), "| autopost:", autopost_enabled())
    print("title:", t)
    print("desc:", d[:120], "…")
    if path:
        print("video_id:", upload_short(path, t, d, tg))
