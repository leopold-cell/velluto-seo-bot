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
HASHTAGS = "#cycling #rennrad #fiets #fietsen"   # fixed set on every reel
REEL_SECONDS = 8   # every reel is hard-cut to this length (video + music)


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

    msg = client.messages.create(
        model=MODEL,
        max_tokens=900,
        temperature=1.0,
        system=(
            "You create Instagram Reels in the EXACT style of @doctor.running — but for ROAD "
            "CYCLISTS (Rennrad), not runners. The format is fixed and non-negotiable:\n"
            "• FACELESS, first-person POV footage looking down the road ahead while riding. No "
            "face, no talking, no skit. The video is just a calm POV road shot.\n"
            "• The whole joke lives in ONE big block of on-screen text that stays up the entire "
            "clip — a relatable first-person confession/thought a roadie has mid-ride. Optionally "
            "a short punchline flips it at the very end.\n"
            "• Voice: dry, self-deprecating, insider. Real roadie culture: the n+1 rule, café "
            "stops, Strava segments & kudos, tan lines, the mate who half-wheels, suffering on "
            "climbs, 'just one more lap', weather denial, pre-ride faff, watts, empty-road bliss.\n"
            "This is NOT marketing: NO product pitch, NO glasses/feature talk, NO CTA. Velluto "
            "(road eyewear) is only a background vibe, never mentioned. The ONE goal: a roadie "
            "reads the text, thinks 'that's literally me', and TAGS a mate or COMMENTS."
        ),
        messages=[{"role": "user", "content": (
            "Write ONE doctor.running-style POV Rennrad Reel (5-8s). Make the on-screen line "
            "SPECIFIC and instantly recognisable, not generic. Output EXACTLY these labelled blocks:\n\n"
            "ONSCREEN: <the ONE on-screen text line that holds the whole clip — first-person, "
            "relatable, max ~12 words. This is the whole joke/hook. e.g. 'me pretending it's a "
            "recovery ride for the 4th day in a row'>\n"
            "PUNCHLINE: <optional short payoff shown in the final ~2s, or '-' if none. max ~8 words>\n"
            "VIDEO_PROMPT: <a SHORT motion prompt for animating a POV road PHOTO (image-to-video). "
            "ONLY a subtle forward camera move — e.g. 'slow steady forward dolly down the empty "
            "road, gentle handheld drift'. Do NOT describe people, riders, hands or pedalling (it "
            "morphs and looks fake). Minimal, grounded, realistic.>\n"
            "CAPTION: <ONE single line only (no line breaks). Relatable and comment-baiting — "
            "ideally end with a QUESTION so people reply. No sales pitch, no link, no product "
            "talk, no hashtags (hashtags are added automatically).>\n"
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


def _pick_music() -> str:
    """Download today's license-free music track and return its local path.

    music_tracks.json = ["https://…mp3", …] or [{"url": "…", "desc": "…"}, …].
    Instagram's own music library is NOT available via the API, so the track is baked
    into the video file. Use only license-free / royalty-free music. '' if none set."""
    try:
        tracks = json.load(open(os.path.join(BASE, "music_tracks.json")))
        urls = [t.get("url") if isinstance(t, dict) else t for t in (tracks or [])]
        urls = [u for u in urls if u]
        if not urls:
            return ""
        url = urls[datetime.date.today().toordinal() % len(urls)]
        import requests
        dest = os.path.join(BASE, "output", "reels", "music_today")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        open(dest, "wb").write(r.content)
        print(f"   ▶ music track from music_tracks.json ({len(urls)} in library)")
        return dest
    except Exception as e:
        print(f"   ⚠️  music skipped: {e}")
        return ""


def _pick_vetted_clip() -> str:
    """Prefer a hand-vetted road-cycling clip from reel_clips.json — the reliable path.
    Same idea as doctor.running: reuse good POV footage, change only the caption daily.
    reel_clips.json = ["https://…mp4", …] or [{"url": "…", "desc": "…"}, …].
    Returns "" if the library is empty (then we fall back to Higgsfield generation)."""
    try:
        clips = json.load(open(os.path.join(BASE, "reel_clips.json")))
        urls = [c.get("url") if isinstance(c, dict) else c for c in (clips or [])]
        urls = [u for u in urls if u]
        if urls:
            pick = urls[datetime.date.today().toordinal() % len(urls)]
            print(f"   ▶ using vetted clip from reel_clips.json ({len(urls)} in library)")
            return pick
    except Exception:
        pass
    return ""


def _pick_start_image() -> str:
    """The start frame MUST be a POV road-ahead shot (pov_images.json) — animating a
    candid rider photo is what produced the morphing 'glidging' clips. Only fall back
    to the candid pool as a last resort, and warn loudly so POV images get generated."""
    try:
        pov = json.load(open(os.path.join(BASE, "pov_images.json")))
        if isinstance(pov, list) and pov:
            return pov[datetime.date.today().toordinal() % len(pov)]
    except Exception:
        pass
    print("   ⚠️  no pov_images.json — falling back to a candid photo (will look off). "
          "Run `python3 generate_pov_images.py` to build the POV road-ahead library.")
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

    # Source the footage: vetted library first (reliable), Higgsfield generation only
    # as a fallback when the library is empty.
    video_prompt = _extract("VIDEO_PROMPT", brief)
    video_url = _pick_vetted_clip()
    if not video_url and video_prompt:
        # Fallback: animate a POV road-ahead photo. Force a POV start frame — a candid
        # rider photo is what produced the morphing/off-topic clips.
        start_image = os.getenv("HIGGSFIELD_IMAGE_URL", "") or _pick_start_image()
        video_url = higgsfield_video.generate_video(
            video_prompt, image_url=start_image, duration=REEL_SECONDS, aspect_ratio="9:16")

    captioned = ""
    captions_burned = False
    if video_url:
        import caption_video
        onscreen  = _extract("ONSCREEN", brief)
        punchline = _extract("PUNCHLINE", brief).strip(" -•\t")
        if punchline in ("-", ""):
            punchline = ""
        out = os.path.join(BASE, "output", "reels", f"reel_{TODAY}.mp4")
        music = _pick_music()   # license-free track baked into the file (no IG music API)
        captioned = caption_video.download_and_caption(
            video_url, onscreen, punchline, out, duration=REEL_SECONDS, music_path=music)
        # captions_burned is True only if the returned file is the captioned one
        # (caption_video returns the *_raw.mp4 path on ffmpeg/font failure).
        captions_burned = bool(captioned) and not captioned.endswith("_raw.mp4")

    video_line = (f"🎬 Reel-Video (Higgsfield): {video_url}" if video_url
                  else "🎬 Reel-Video: nicht erzeugt (HIGGSFIELD_API_KEY in .env setzen).")
    if captioned and captions_burned:
        video_line += f"\n🎬 Mit Text-Overlay (auf VPS): {captioned}"
    elif video_url and not captions_burned:
        video_line += ("\n⚠️  TEXT-OVERLAY FEHLT — ffmpeg ist auf dem VPS nicht installiert. "
                       "Fix: `apt install ffmpeg -y`. Ohne ffmpeg wird nur der rohe Clip verschickt.")

    # ── Auto-post to Instagram (Graph API). No-op/dry-run until BOTH the IG creds
    # (instagram_auth.py) AND IG_AUTOPOST=1 are set — i.e. TEST-MODE by default.
    post_line = "📮 Instagram: TEST-MODE (kein Auto-Posting)."
    # Never publish a caption-less clip — the on-screen text IS the content. Override
    # this safety with REEL_ALLOW_NO_CAPTION=1 if you ever want raw clips posted.
    if video_url and not captions_burned and \
       os.getenv("REEL_ALLOW_NO_CAPTION", "").strip() not in ("1", "true", "yes", "on"):
        post_line = ("📮 Instagram: ⛔ nicht gepostet — Text-Overlay fehlt (ffmpeg auf dem VPS "
                     "installieren: `apt install ffmpeg -y`). Ohne Overlay kein Post.")
    elif video_url:
        import instagram_post
        if instagram_post.is_configured():
            # Always: one-line, relatable caption + the four fixed hashtags.
            line = " ".join(_extract("CAPTION", brief).split())   # collapse to a single line
            ig_caption = f"{line}\n\n{HASHTAGS}".strip()
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
