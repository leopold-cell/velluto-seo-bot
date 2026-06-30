"""
Higgsfield Soul text-to-image client — generate organic photos (e.g. POV road
cycling) used as start frames for Reels.

Same platform as higgsfield_video: endpoint = base + "/" + model path, auth via
hf-api-key + hf-secret headers, async (queued → status_url → image URL).

  HIGGSFIELD_API_KEY / HIGGSFIELD_API_SECRET   # shared with the video client
  HIGGSFIELD_IMAGE_MODEL  # default higgsfield-ai/soul/v2/standard

No-op (returns "") when creds are missing.
"""
from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

import higgsfield_video as hv   # reuse poll_for_url + URL extractors

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)


def generate_image(prompt: str, aspect_ratio: str = "9:16", resolution: str = "720p") -> str:
    """Generate one image from a prompt via Higgsfield Soul. Returns the image URL or ""."""
    key_id = os.getenv("HIGGSFIELD_API_KEY", "")
    secret = os.getenv("HIGGSFIELD_API_SECRET", "")
    if not (key_id and secret):
        print("   🖼  image skip — HIGGSFIELD_API_KEY / HIGGSFIELD_API_SECRET not set")
        return ""
    base  = os.getenv("HIGGSFIELD_API_BASE", "https://platform.higgsfield.ai").rstrip("/")
    model = os.getenv("HIGGSFIELD_IMAGE_MODEL", "higgsfield-ai/soul/v2/standard")
    headers = {"hf-api-key": key_id, "hf-secret": secret, "Content-Type": "application/json"}
    body = {
        "prompt": prompt,
        "batch_size": 1,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "enhance_prompt": True,
    }
    try:
        r = requests.post(f"{base}/{model.lstrip('/')}", headers=headers, json=body, timeout=60)
    except Exception as e:
        print(f"   ⚠️  soul submit error: {e}")
        return ""
    if r.status_code >= 300:
        print(f"   ⚠️  soul {model} submit failed {r.status_code}: {r.text[:400]}")
        return ""

    resp = r.json() if r.content else {}
    img = hv._extract_url(resp) or hv._find_any_url(resp, "image")
    # If the submit already returned an image URL (sync), use it.
    if img and (".jpg" in img.lower() or ".png" in img.lower() or ".webp" in img.lower()):
        print(f"   ✓ soul image ready: {img[:70]}…")
        return img

    status_url = resp.get("status_url") or hv._dig(resp, "data", "status_url")
    if not status_url:
        print(f"   ⚠️  soul: no status_url in response: {str(resp)[:300]}")
        return ""
    job = resp.get("request_id") or resp.get("id")
    print(f"   🖼  soul job {job} queued — polling…")
    url = hv.poll_for_url(status_url, headers, kind="image")
    if url:
        print(f"   ✓ soul image ready: {url[:70]}…")
    return url
