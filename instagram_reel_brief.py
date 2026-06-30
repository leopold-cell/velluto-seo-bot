#!/usr/bin/env python3
"""
Daily Instagram REEL brief generator (TEST MODE — email only, no posting).

Turns today's published blog topic into a short-form, meme-leaning Reel concept for
road-cyclists (rennrad) and emails it to Leopold for review/manual posting. This is
the creative foundation that EVERY posting path needs; actual auto-publishing (via
the official Instagram Graph API) is a separate, later step.

Output per day: hook, on-screen text beats (the meme arc), a phone-filmable shot
idea, a caption with a soft StradaPro CTA, and hashtags — emailed via mailer.py.

Run:  python3 instagram_reel_brief.py            # generate + email one brief
Safe: no Instagram API, no posting. No-op if no article/credentials.
"""
from __future__ import annotations

import datetime
import json
import os
import re

from dotenv import load_dotenv

import mailer
import higgsfield_video

BASE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(BASE, ".env"), override=True)

TODAY = datetime.date.today().isoformat()
MODEL = "claude-sonnet-4-6"   # creative copy — wit matters more than cost here


def _todays_topic() -> dict:
    """Pick today's published article as the reel source; fall back to a dynamic topic."""
    try:
        pub = json.load(open(os.path.join(BASE, "published_today.json")))
        if isinstance(pub, list) and pub:
            a = pub[-1]
            return {"title": a.get("title", ""), "topic": a.get("topic", ""),
                    "keyword": a.get("keyword", "")}
    except Exception:
        pass
    try:
        dyn = json.load(open(os.path.join(BASE, "topics_dynamic.json")))
        t = (dyn[0] if isinstance(dyn, list) and dyn else {}) or {}
        return {"title": "", "topic": t.get("topic", ""), "keyword": t.get("topic", "")}
    except Exception:
        return {"title": "", "topic": "premium road cycling glasses", "keyword": "cycling glasses"}


def build_brief(topic: dict) -> str:
    from anthropic import Anthropic
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Rotate the format daily so the feed mixes faceless / POV / face content.
    formats = [
        "FACELESS — text/voiceover over POV or scenery footage, no person on camera",
        "POV RIDING — helmet- or handlebar-POV, the rider's-eye view, in-the-saddle",
        "FACE — talking/reacting to camera (piece-to-camera, skit, or duet-style)",
    ]
    fmt = formats[datetime.date.today().toordinal() % len(formats)]

    msg = client.messages.create(
        model=MODEL,
        max_tokens=900,
        temperature=1.0,
        system=(
            "You are a viral social creative for ROAD CYCLISTS (Rennrad). You make HUMOROUS, "
            "relatable, lifestyle Instagram Reels — the kind a cyclist sends to the group chat or "
            "tags a mate on, captioned 'this is literally us'. Pure cyclist culture & inside jokes: "
            "the n+1 rule, café stops, Strava kudos & segment hunting, ridiculous tan lines, the "
            "friend who always half-wheels, suffering on climbs, kit/sock-height debates, weather "
            "denial, marginal-gains nonsense, 'just one more lap', pre-ride faff, etc. "
            "This is NOT product marketing: NO feature pitches, NO 'your glasses fog up' angles, NO "
            "sales talk, NO CTAs. The brand behind it is Velluto (road eyewear) but it stays in the "
            "background as vibe only, never a pitch. The ONE goal: make road cyclists laugh and COMMENT."
        ),
        messages=[{"role": "user", "content": (
            f"Reel format for today: {fmt}\n\n"
            "Write ONE short Reel concept (8-15s) in that format. Make it SPECIFIC and fresh — a real, "
            "instantly-recognisable road-cyclist moment, not generic. Output EXACTLY these labelled blocks:\n\n"
            "HOOK: <on-screen text or spoken line for the first 1.5s — must stop the scroll>\n"
            f"FORMAT: <{fmt}>\n"
            "BEATS: <3-5 short beats (on-screen text / action / spoken line) building to the funny payoff, one per line>\n"
            "SHOT: <how to film it on a phone in this format — simple and doable>\n"
            "VIDEO_PROMPT: <one vivid 1-2 sentence prompt for an AI video generator: a cinematic road-cycling "
            "visual with camera motion, no on-screen text, just the scene>\n"
            "CAPTION: <a funny, relatable caption that BAITS comments — end with a question or 'tag the friend who…'. "
            "No sales pitch, no link, no product talk.>\n"
            "HASHTAGS: <10-12 hashtags, mix EN + DE rennrad / cycling-culture, space-separated>\n"
        )}],
    )
    return msg.content[0].text.strip()


def _extract(label: str, text: str) -> str:
    m = re.search(rf"{label}:\s*(.+?)(?:\n[A-Z_]+:|\Z)", text, re.S)
    return m.group(1).strip() if m else ""


# Candid / UGC rider photos (Shopify CDN) used as the start frame — chosen to look
# ORGANIC, NOT branded: no logo banners, no marketing text, no product-on-white
# catalog shots. Override any day with HIGGSFIELD_IMAGE_URL, or add your own
# organic shots (e.g. from velluto.cc Instagram) here.
_IMAGE_POOL = [
    "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Lifestyle_mobileUGC.webp",
    "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Lifestyle_1x1_fe573806-27fe-4b9d-8be3-be91c2f1aadb.webp",
    "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Rick_Arancia.webp",
    "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_3.webp",
    "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_6.webp",
    "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_9.webp",
    "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_12.webp",
    "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_16.webp",
    "https://cdn.shopify.com/s/files/1/0621/5607/9275/files/Review_18.jpg",
]


def _pick_start_image() -> str:
    """Prefer generated POV cycling images (pov_images.json); else the candid pool."""
    try:
        pov = json.load(open(os.path.join(BASE, "pov_images.json")))
        if isinstance(pov, list) and pov:
            return pov[datetime.date.today().toordinal() % len(pov)]
    except Exception:
        pass
    return _IMAGE_POOL[datetime.date.today().toordinal() % len(_IMAGE_POOL)]


def main():
    topic = _todays_topic()
    try:
        brief = build_brief(topic)
    except Exception as e:
        print(f"   ⚠️  reel brief generation failed: {e}")
        return

    # Generate the Reel video via Higgsfield (no-op + note if no API key).
    video_prompt = _extract("VIDEO_PROMPT", brief)
    video_url = ""
    if video_prompt:
        start_image = os.getenv("HIGGSFIELD_IMAGE_URL", "") or _pick_start_image()
        video_url = higgsfield_video.generate_video(
            video_prompt, image_url=start_image, duration=8, aspect_ratio="9:16")
    video_line = (f"🎬 Reel-Video (Higgsfield): {video_url}" if video_url
                  else "🎬 Reel-Video: nicht erzeugt (HIGGSFIELD_API_KEY in .env setzen).")

    body = (
        "TEST-MODE · Instagram Reel (noch kein Auto-Posting)\n"
        f"Quelle: {topic.get('title') or topic.get('topic')}\n\n"
        f"{video_line}\n"
        "────────────────────────────────────────\n\n"
        f"{brief}\n\n"
        "────────────────────────────────────────\n"
        "Video passt? Dann verdrahte ich das Reels-Posting (offizielle Instagram Graph API), "
        "sobald dein Meta-Business/App-Setup steht."
    )
    subject = f"🎬 Velluto Reel (Test) — {TODAY}"
    mailer.send_email(subject, body)


if __name__ == "__main__":
    main()
