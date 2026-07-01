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
STATE = os.path.join(BASE, "reel_state.json")


def _already_posted_today() -> bool:
    """True if a reel was already published today — keeps it to 1×/day even if
    run.sh fires twice. Only a successful post is recorded, so dry-runs never block.
    Override with REEL_FORCE=1 for manual re-tests."""
    if os.getenv("REEL_FORCE", "").strip() in ("1", "true", "yes", "on"):
        return False
    try:
        return json.load(open(STATE)).get("last_post_date") == TODAY
    except Exception:
        return False


def _record_post(media_id: str):
    try:
        json.dump({"last_post_date": TODAY, "last_media_id": media_id},
                  open(STATE, "w"), indent=2)
    except Exception:
        pass


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
            "VIDEO_PROMPT: <a SHORT motion prompt for animating a POV road PHOTO (image-to-video). Describe "
            "ONLY a subtle, natural camera move — e.g. 'slow steady forward dolly down the road, gentle drift, "
            "realistic handheld'. Do NOT describe people, riders or pedalling (it morphs and looks fake). Keep "
            "the motion minimal and grounded.>\n"
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
    # 1×/day: if we already posted today, skip the whole run (saves Higgsfield credits
    # + Claude tokens). Dry-runs don't record, so testing stays unaffected.
    if _already_posted_today():
        print(f"   ▶ reel skip — already posted today ({TODAY}). REEL_FORCE=1 to override.")
        return

    topic = _todays_topic()
    try:
        brief = build_brief(topic)
    except Exception as e:
        print(f"   ⚠️  reel brief generation failed: {e}")
        return

    # Generate the Reel video via Higgsfield (no-op + note if no API key).
    video_prompt = _extract("VIDEO_PROMPT", brief)
    video_url = ""
    captioned = ""
    if video_prompt:
        start_image = os.getenv("HIGGSFIELD_IMAGE_URL", "") or _pick_start_image()
        video_url = higgsfield_video.generate_video(
            video_prompt, image_url=start_image, duration=5, aspect_ratio="9:16")
        if video_url:
            import caption_video
            hook  = _extract("HOOK", brief)
            beats = [b.strip(" -•\t") for b in _extract("BEATS", brief).splitlines() if b.strip()]
            out   = os.path.join(BASE, "output", "reels", f"reel_{TODAY}.mp4")
            captioned = caption_video.download_and_caption(video_url, hook, beats, out, duration=5)

    video_line = (f"🎬 Reel-Video (Higgsfield): {video_url}" if video_url
                  else "🎬 Reel-Video: nicht erzeugt (HIGGSFIELD_API_KEY in .env setzen).")
    if captioned:
        video_line += f"\n🎬 Mit Captions (auf VPS): {captioned}"

    # ── Auto-post to Instagram (Graph API). No-op/dry-run until BOTH the IG creds
    # (instagram_auth.py) AND IG_AUTOPOST=1 are set — i.e. TEST-MODE by default.
    post_line = "📮 Instagram: TEST-MODE (kein Auto-Posting)."
    if video_url:
        import instagram_post
        if instagram_post.is_configured():
            ig_caption = _extract("CAPTION", brief)
            tags = _extract("HASHTAGS", brief)
            if tags:
                ig_caption = f"{ig_caption}\n\n{tags}".strip()
            # Host the CAPTIONED clip on Drive; fall back to the raw Higgsfield URL.
            public_url = ""
            if captioned and os.path.isfile(captioned):
                import drive_upload
                public_url = drive_upload.upload_public(captioned, name=f"velluto_reel_{TODAY}.mp4")
            public_url = public_url or video_url
            media_id = instagram_post.publish_reel(public_url, ig_caption)
            if media_id:
                _record_post(media_id)
                mode = "Test-Reel (nur Nicht-Follower)" if instagram_post.trial_enabled() else "Reel"
                post_line = f"📮 Instagram: ✅ als {mode} gepostet (media id {media_id})\n   Quelle: {public_url}"
            elif instagram_post.autopost_enabled():
                post_line = "📮 Instagram: ⚠️ Posting fehlgeschlagen — siehe VPS-Log."
            else:
                post_line = ("📮 Instagram: bereit, aber DRY-RUN (IG_AUTOPOST≠1). "
                             "Zum Scharfschalten IG_AUTOPOST=1 in .env setzen.")
        else:
            post_line = ("📮 Instagram: Token fehlt — einmalig `python3 instagram_auth.py` "
                         "laufen lassen (IG_ACCESS_TOKEN + IG_USER_ID).")

    body = (
        f"Instagram Reel — {TODAY}\n"
        f"Quelle: {topic.get('title') or topic.get('topic')}\n\n"
        f"{video_line}\n"
        f"{post_line}\n"
        "────────────────────────────────────────\n\n"
        f"{brief}\n"
    )
    subject = f"🎬 Velluto Reel — {TODAY}"
    attach = [captioned] if (captioned and os.path.isfile(captioned)) else None
    mailer.send_email(subject, body, attachments=attach)


if __name__ == "__main__":
    main()
