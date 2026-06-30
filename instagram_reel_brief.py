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
    src = topic.get("title") or topic.get("topic") or topic.get("keyword")

    msg = client.messages.create(
        model=MODEL,
        max_tokens=900,
        system=(
            "You are the social creative for Velluto, a premium road-cycling eyewear brand "
            "(StradaPro glasses: 25g, click-in interchangeable VellutoPuro clear + VellutoVisione "
            "high-contrast lenses, anti-fog, UV400, 30-day risk-free trial). "
            "You write short-form Instagram REELS for road cyclists (Rennrad). Tone: relatable, "
            "witty, meme-leaning — like a rider who gets the inside jokes — but every reel lands a "
            "real, useful point and a soft product tie-in. Never cringe, never hard-sell."
        ),
        messages=[{"role": "user", "content": (
            f"Today's topic: {src}\n\n"
            "Write ONE Reel concept (a single short video, 8-15s). Output EXACTLY these labelled blocks:\n\n"
            "HOOK: <on-screen text for the first 1.5s — must stop the scroll>\n"
            "BEATS: <3-4 short on-screen text lines that carry the joke/arc to the payoff, one per line>\n"
            "SHOT: <one phone-filmable visual idea: rider POV / bike computer / glasses, simple to shoot>\n"
            "VIDEO_PROMPT: <a single vivid text-to-video prompt (1-2 sentences) describing the cycling "
            "scene with motion and camera move, for an AI video generator. No on-screen text, no captions, "
            "just the visual. Cinematic, real road-cycling look.>\n"
            "CAPTION: <relatable 2-3 sentence caption, soft CTA to StradaPro, 'Link in Bio'>\n"
            "HASHTAGS: <10-12 hashtags, mix EN + DE rennrad, space-separated>\n"
        )}],
    )
    return msg.content[0].text.strip()


def _extract(label: str, text: str) -> str:
    m = re.search(rf"{label}:\s*(.+?)(?:\n[A-Z_]+:|\Z)", text, re.S)
    return m.group(1).strip() if m else ""


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
        video_url = higgsfield_video.generate_video(video_prompt, duration=8, aspect_ratio="9:16")
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
