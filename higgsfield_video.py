"""
Higgsfield video API client — text-to-video for Instagram Reels.

Async flow: POST a generation, poll until complete, return the output video URL.
Built configurable + defensive because the exact endpoint/field names differ by
Higgsfield access tier (official cloud vs gateways); tune via env if needed:

  HIGGSFIELD_API_KEY      # required — key ID   (sent as header hf-api-key)
  HIGGSFIELD_API_SECRET   # required — key secret (sent as header hf-secret)
  HIGGSFIELD_API_BASE     # default https://platform.higgsfield.ai
  HIGGSFIELD_VIDEO_MODEL  # default higgsfield-ai/dop/turbo (image-to-video)
  HIGGSFIELD_IMAGE_URL    # start frame for image-to-video (a Velluto image)

No-op (returns "") when key/secret/image are missing, so the pipeline never breaks.
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
        os.getenv("HIGGSFIELD_API_BASE", "https://platform.higgsfield.ai").rstrip("/"),
        # Model path appended to the base as the endpoint (per Higgsfield's API).
        # DoP Turbo = fast image-to-video. Override via HIGGSFIELD_VIDEO_MODEL.
        os.getenv("HIGGSFIELD_VIDEO_MODEL", "higgsfield-ai/dop/turbo"),
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


def generate_video(prompt: str, image_url: str = "", duration: int = 8,
                   aspect_ratio: str = "9:16") -> str:
    """Higgsfield DoP image-to-video: animate a still (image_url) into a 9:16 clip.
    Endpoint = base + "/" + model path (e.g. .../higgsfield-ai/dop/turbo); auth via
    hf-api-key + hf-secret headers. Returns the video URL or "". Logs the full
    response so the (async) result/poll shape can be finalized on the first run."""
    key_id, secret, base, model = _cfg()
    if not (key_id and secret):
        print("   🎬 video skip — HIGGSFIELD_API_KEY / HIGGSFIELD_API_SECRET not set in .env")
        return ""
    image_url = image_url or os.getenv("HIGGSFIELD_IMAGE_URL", "")
    if not image_url:
        print("   🎬 video skip — no start image (set HIGGSFIELD_IMAGE_URL or pass image_url)")
        return ""

    url = f"{base}/{model.lstrip('/')}"
    headers = {"hf-api-key": key_id, "hf-secret": secret, "Content-Type": "application/json"}
    body = {
        "image_url": image_url,       # DoP image-to-video requires this exact field
        "prompt": prompt,
        "motions": [],
        "enhance_prompt": True,
        "aspect_ratio": aspect_ratio,
        "duration": duration,
    }
    try:
        r = requests.post(url, headers=headers, json=body, timeout=60)
    except Exception as e:
        print(f"   ⚠️  higgsfield submit error: {e}")
        return ""
    if r.status_code >= 300:
        print(f"   ⚠️  higgsfield {model} submit failed {r.status_code}: {r.text[:400]}")
        return ""

    resp = r.json() if r.content else {}
    # Sync result?
    vid = _extract_url(resp) or _extract_url(resp.get("data") or {})
    if vid:
        print(f"   ✓ higgsfield video ready: {vid[:60]}…")
        return vid

    # Async: log the response so we can wire the exact poll endpoint/field next.
    job = (resp.get("id") or resp.get("request_id") or resp.get("job_id")
           or _dig(resp, "data", "id"))
    print(f"   🎬 higgsfield accepted (job={job}). Response shape: {str(resp)[:400]}")
    print("   ℹ️  (image-to-video is async — send this response so the poll step can be finalized)")
    return ""
