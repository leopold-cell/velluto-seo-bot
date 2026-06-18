#!/usr/bin/env python3
"""
AI cover-image generator for blog posts.

The curated WHITELIST pool in seo_bot.py is finite (~50 images) and visibly
repeats as the blog grows. This module generates a fresh, topic-specific,
on-brand cover image per post via the OpenAI Images API and hosts it on the
Shopify Files CDN, so the pool never runs out.

Runtime: the autonomous bot (VPS cron) can call this from Python — it does NOT
use any MCP. OPENAI_API_KEY + SHOPIFY_TOKEN are already configured.

Usage:
  python3 image_generator.py --topic "cycling glasses for narrow faces"   # 1 image → prints CDN url
  python3 image_generator.py --batch 8                                     # top-up: N pool images
  python3 image_generator.py --topic "..." --dry-run                       # build prompt only, no API
"""
from __future__ import annotations

import argparse
import base64
import datetime as _dt
import json
import os
import re
import time

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
                override=False)
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
GEN_LOG = os.path.join(ROOT, "images_gen_log.json")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN", "")
SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "velluto-brand.myshopify.com")
SHOPIFY_HEADERS = {"X-Shopify-Access-Token": SHOPIFY_TOKEN, "Content-Type": "application/json"}
API = "https://%s/admin/api/2024-01/graphql.json" % SHOPIFY_STORE


# ── config ──────────────────────────────────────────────────────────────────

def config() -> dict:
    defaults = {
        "generate": True,
        "model": "gpt-image-1",
        "size": "1536x1024",          # landscape ~16/9 for the hero figure
        "cost_per_image_usd": 0.17,
        "monthly_budget_usd": 30.0,
        "filename_prefix": "ai-cover",
    }
    try:
        import config_loader
        raw = (config_loader._load("publishing_rules") or {}).get("images") or {}
        defaults.update({k: v for k, v in raw.items() if v is not None})
    except Exception:
        pass
    return defaults


# ── budget guard ────────────────────────────────────────────────────────────

def _month() -> str:
    return _dt.date.today().strftime("%Y-%m")


def _load_gen_log() -> dict:
    if os.path.exists(GEN_LOG):
        try:
            return json.load(open(GEN_LOG))
        except Exception:
            return {}
    return {}


def budget_remaining() -> float:
    cfg = config()
    spent = _load_gen_log().get(_month(), {}).get("cost_usd", 0.0)
    return cfg["monthly_budget_usd"] - spent


def _record_spend(cost: float) -> None:
    log = _load_gen_log()
    m = log.setdefault(_month(), {"count": 0, "cost_usd": 0.0})
    m["count"] += 1
    m["cost_usd"] = round(m["cost_usd"] + cost, 4)
    with open(GEN_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)


# ── prompt ──────────────────────────────────────────────────────────────────

# Velluto sells UV400 cycling eyewear (StradaPro shield) + interchangeable lenses.
# NOT photochromic, NOT polarized, NOT prescription — never depict text/claims.
def build_prompt(topic: str) -> str:
    topic = (topic or "cycling glasses").strip()
    return (
        "Editorial photograph for a premium cycling-eyewear magazine. "
        f"Scene inspired by the topic: \"{topic}\". "
        "A road cyclist wearing modern shield-style sport sunglasses, dynamic outdoor "
        "cycling setting (open road, mountain pass or coastal route), natural golden-hour "
        "light, shallow depth of field, high-end athletic apparel, premium and aspirational "
        "mood. Photorealistic, sharp, professional sports-lifestyle photography. "
        "No text, no logos, no watermarks, no brand names, no UI graphics. "
        "Do not show price tags or written claims."
    )


def alt_text(topic: str) -> str:
    t = re.sub(r"\s+", " ", (topic or "cycling glasses")).strip().rstrip(".")
    return f"Road cyclist wearing Velluto cycling glasses — {t}"[:120]


def _slug(topic: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (topic or "cover").lower()).strip("-")
    return s[:40] or "cover"


# ── OpenAI image generation ─────────────────────────────────────────────────

def generate_image_bytes(prompt: str) -> bytes | None:
    if not OPENAI_API_KEY:
        print("   ⚠️  image_generator: OPENAI_API_KEY missing")
        return None
    cfg = config()
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.images.generate(model=cfg["model"], prompt=prompt,
                                       size=cfg["size"], n=1)
        b64 = resp.data[0].b64_json
        return base64.b64decode(b64)
    except Exception as e:
        print(f"   ⚠️  image_generator: OpenAI generation failed: {e}")
        return None


# ── Shopify Files upload (staged upload → fileCreate → poll) ─────────────────

def _gql(query: str, variables: dict) -> dict:
    r = requests.post(API, headers=SHOPIFY_HEADERS,
                      json={"query": query, "variables": variables}, timeout=30)
    return r.json().get("data", {}) or {}


_STAGED = """
mutation stagedUploadsCreate($input: [StagedUploadInput!]!) {
  stagedUploadsCreate(input: $input) {
    stagedTargets { url resourceUrl parameters { name value } }
    userErrors { field message }
  }
}"""

_FILECREATE = """
mutation fileCreate($files: [FileCreateInput!]!) {
  fileCreate(files: $files) {
    files { id fileStatus alt ... on MediaImage { image { url } } }
    userErrors { field message }
  }
}"""

_NODE = """
query($id: ID!) {
  node(id: $id) { ... on MediaImage { id fileStatus image { url } } }
}"""


def upload_to_shopify_files(img: bytes, filename: str, alt: str = "") -> str | None:
    """Upload bytes to Shopify Files, return the permanent CDN URL (or None)."""
    if not SHOPIFY_TOKEN:
        print("   ⚠️  image_generator: SHOPIFY_TOKEN missing — cannot host image")
        return None
    # 1) staged target
    data = _gql(_STAGED, {"input": [{
        "filename": filename, "mimeType": "image/png",
        "httpMethod": "POST", "resource": "FILE",
    }]})
    sc = (data.get("stagedUploadsCreate") or {})
    if sc.get("userErrors"):
        print(f"   ⚠️  stagedUploadsCreate errors: {sc['userErrors']}")
        return None
    targets = sc.get("stagedTargets") or []
    if not targets:
        return None
    target = targets[0]
    # 2) POST the bytes to the staged target
    form = [(p["name"], p["value"]) for p in target.get("parameters", [])]
    try:
        up = requests.post(target["url"], data=form,
                          files={"file": (filename, img, "image/png")}, timeout=60)
        if up.status_code not in (200, 201, 204):
            print(f"   ⚠️  staged upload PUT failed: HTTP {up.status_code}")
            return None
    except Exception as e:
        print(f"   ⚠️  staged upload error: {e}")
        return None
    # 3) fileCreate referencing the resource URL
    data = _gql(_FILECREATE, {"files": [{
        "originalSource": target["resourceUrl"], "contentType": "IMAGE",
        "alt": alt[:512],
    }]})
    fc = (data.get("fileCreate") or {})
    if fc.get("userErrors"):
        print(f"   ⚠️  fileCreate errors: {fc['userErrors']}")
        return None
    files = fc.get("files") or []
    if not files:
        return None
    node = files[0]
    url = (node.get("image") or {}).get("url")
    if url:
        return url
    # 4) poll until processed
    fid = node.get("id")
    for _ in range(15):
        time.sleep(2)
        nd = (_gql(_NODE, {"id": fid}).get("node") or {})
        if nd.get("fileStatus") == "READY":
            return (nd.get("image") or {}).get("url")
        if nd.get("fileStatus") == "FAILED":
            return None
    return None


# ── orchestration ───────────────────────────────────────────────────────────

def generate_cover(topic: str, keyword: str | None = None) -> str | None:
    """Generate + host one cover image for a post. Returns CDN URL or None
    (caller falls back to the curated pool)."""
    cfg = config()
    if not cfg.get("generate"):
        return None
    if budget_remaining() < cfg["cost_per_image_usd"]:
        print(f"   ⚠️  image_generator: monthly image budget reached — using pool")
        return None
    prompt = build_prompt(keyword or topic)
    img = generate_image_bytes(prompt)
    if not img:
        return None
    _record_spend(cfg["cost_per_image_usd"])
    ts = _dt.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"{cfg['filename_prefix']}-{_slug(keyword or topic)}-{ts}.png"
    url = upload_to_shopify_files(img, filename, alt=alt_text(keyword or topic))
    if url:
        print(f"   ✓ AI cover generated: {url}")
    return url


def batch(n: int) -> list[str]:
    """Top-up: generate N generic on-brand pool images. Returns CDN URLs."""
    seeds = [
        "road cyclist on a mountain pass at sunrise",
        "close-up of cycling shield sunglasses on a bike handlebar",
        "female cyclist on a coastal road, dynamic motion",
        "gravel cyclist in golden-hour light",
        "pro peloton detail, eyewear focus",
        "cyclist climbing an alpine switchback",
        "studio product shot of sport shield sunglasses",
        "urban commuter cyclist at dawn",
        "cyclist descending fast, wind and speed",
        "mountain biker on a forest trail",
        "cyclist resting, lifestyle editorial",
        "macro of interchangeable cycling lenses",
    ]
    urls = []
    for i in range(min(n, len(seeds))):
        print(f"[{i+1}/{min(n,len(seeds))}] {seeds[i]}")
        u = generate_cover(seeds[i], seeds[i])
        if u:
            urls.append(u)
        time.sleep(2)
    return urls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", type=str)
    ap.add_argument("--batch", type=int)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.dry_run:
        print("PROMPT:\n" + build_prompt(args.topic or "cycling glasses"))
        print("\nALT:", alt_text(args.topic or "cycling glasses"))
        print("Budget remaining this month: $%.2f" % budget_remaining())
        return
    if args.batch:
        urls = batch(args.batch)
        print(json.dumps(urls, indent=2))
    elif args.topic:
        url = generate_cover(args.topic, args.topic)
        print(url or "FAILED — fell back to pool")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
