"""
Higgsfield video API client — text-to-video for Instagram Reels.

Async flow: POST a generation, poll until complete, return the output video URL.
Built configurable + defensive because the exact endpoint/field names differ by
Higgsfield access tier (official cloud vs gateways); tune via env if needed:

  HIGGSFIELD_API_KEY      # required — key ID   (Authorization: Key ID:SECRET)
  HIGGSFIELD_API_SECRET   # required — key secret
  HIGGSFIELD_API_BASE     # default https://platform.higgsfield.ai/v1
  HIGGSFIELD_VIDEO_MODEL  # default higgsfield_v1

No-op (returns "") when key/secret are missing, so the pipeline never breaks.
"""
from __future__ import annotations

import os
import time

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)

POLL_INTERVAL = 8       # seconds between status checks
POLL_TIMEOUT  = 600     # give up after 10 min


def _cfg() -> tuple[str, str, str, str]:
    # Higgsfield auth is a KEY-ID + SECRET pair (Authorization: Key ID:SECRET),
    # not a single bearer token.
    return (
        os.getenv("HIGGSFIELD_API_KEY", ""),     # key id
        os.getenv("HIGGSFIELD_API_SECRET", ""),  # secret
        os.getenv("HIGGSFIELD_API_BASE", "https://platform.higgsfield.ai/v1").rstrip("/"),
        os.getenv("HIGGSFIELD_VIDEO_MODEL", "higgsfield_v1"),
    )


def _dig(d, *path):
    cur = d
    for k in path:
        try:
            cur = cur[k]
        except Exception:
            return None
    return cur


def _extract_url(d: dict) -> str:
    """Find the finished video URL across the response shapes different tiers use."""
    candidates = [
        ("output_url",), ("video_url",), ("url",),
        ("output", "url"), ("result", "url"), ("result", "video_url"),
        ("data", "output_url"), ("data", "url"), ("assets", 0, "url"),
        ("outputs", 0, "url"), ("output", 0, "url"),
    ]
    for path in candidates:
        v = _dig(d, *path)
        if isinstance(v, str) and v.startswith("http"):
            return v
    return ""


def generate_video(prompt: str, duration: int = 8, aspect_ratio: str = "9:16") -> str:
    """Generate a Reel-format (9:16) clip from a text prompt. Returns the video URL
    or "" on failure. Logs the raw server response on error so the field names can
    be aligned to your account's API."""
    key_id, secret, base, model = _cfg()
    if not (key_id and secret):
        print("   🎬 video skip — HIGGSFIELD_API_KEY / HIGGSFIELD_API_SECRET not set in .env")
        return ""
    headers = {"Authorization": f"Key {key_id}:{secret}", "Content-Type": "application/json"}
    body = {
        "task": "text-to-video",
        "model": model,
        "prompt": prompt,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
    }
    try:
        r = requests.post(f"{base}/generations", headers=headers, json=body, timeout=30)
    except Exception as e:
        print(f"   ⚠️  higgsfield submit error: {e}")
        return ""
    if r.status_code >= 300:
        print(f"   ⚠️  higgsfield submit failed {r.status_code}: {r.text[:300]}")
        return ""
    resp = r.json() if r.content else {}
    gid = (resp.get("id") or resp.get("generation_id")
           or _dig(resp, "data", "id") or _dig(resp, "generation", "id"))
    if not gid:
        print(f"   ⚠️  higgsfield: no generation id in response: {str(resp)[:300]}")
        return ""

    print(f"   🎬 higgsfield job {gid} submitted — polling…")
    waited = 0
    while waited < POLL_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL
        try:
            s = requests.get(f"{base}/generations/{gid}", headers=headers, timeout=30)
        except Exception:
            continue
        if s.status_code >= 300:
            continue
        d = s.json() if s.content else {}
        status = str(d.get("status") or d.get("state") or _dig(d, "data", "status") or "").lower()
        if status in ("completed", "succeeded", "success", "done", "finished"):
            url = _extract_url(d) or _extract_url(d.get("data") or {})
            if url:
                print(f"   ✓ higgsfield video ready: {url[:60]}…")
            else:
                print(f"   ⚠️  higgsfield completed but no URL found: {str(d)[:300]}")
            return url
        if status in ("failed", "error", "cancelled", "canceled"):
            print(f"   ⚠️  higgsfield job {status}: {str(d)[:300]}")
            return ""
    print("   ⚠️  higgsfield poll timed out (10 min)")
    return ""
