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
REEL_SECONDS = 14   # every reel is standardised to this length (video + music)


def _current_slot() -> tuple:
    """Which of the 3 daily posting slots we're in, by local hour. Returns
    (name, index): morning<11:00, noon<16:00, else evening."""
    h = datetime.datetime.now().hour
    if h < 11:
        return ("morning", 0)
    if h < 16:
        return ("noon", 1)
    return ("evening", 2)


def _slot_seed() -> int:
    """Rotation seed unique per (day, slot) so each of the 3 daily reels uses a
    different clip/track."""
    return datetime.date.today().toordinal() * 3 + _current_slot()[1]


def _load_state() -> dict:
    try:
        st = json.load(open(STATE))
    except Exception:
        st = {}
    if st.get("date") != TODAY:      # reset slots each day, keep cross-day memory
        st = {"date": TODAY, "slots": [], "recent_lines": st.get("recent_lines", [])}
    st.setdefault("recent_lines", [])
    return st


def _recent_lines() -> list:
    """Last on-screen lines used (kept across days) — fed to the model so openings
    don't repeat (e.g. everything starting with 'told myself…')."""
    return _load_state().get("recent_lines", [])[-10:]


def _remember_line(line: str):
    try:
        st = _load_state()
        if line:
            st["recent_lines"] = (st.get("recent_lines", []) + [line])[-15:]
        json.dump(st, open(STATE, "w"), indent=2)
    except Exception:
        pass


def _already_posted_slot() -> bool:
    """True if THIS slot already posted today — keeps it to one post per slot even if
    the cron fires twice. Only a successful post is recorded, so dry-runs never block.
    Override with REEL_FORCE=1 for manual re-tests."""
    if os.getenv("REEL_FORCE", "").strip() in ("1", "true", "yes", "on"):
        return False
    return _current_slot()[0] in _load_state().get("slots", [])


def _record_post(media_id: str):
    try:
        st = _load_state()
        slot = _current_slot()[0]
        if slot not in st["slots"]:
            st["slots"].append(slot)
        st["last_media_id"] = media_id
        json.dump(st, open(STATE, "w"), indent=2)
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

    recent = _recent_lines()   # avoid repeating openings (e.g. endless "told myself…")
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
            "SPECIFIC and instantly recognisable, not generic.\n\n"
            "VARIETY IS CRITICAL — vary the sentence STRUCTURE, not just the topic. Rotate "
            "between patterns like: 'me pretending…', 'when the group ride…', 'nobody: / my "
            "legs at km 2:'-style setups (as plain prose), 'the moment you realise…', 'POV-free "
            "plain confessions ('I own four bikes and ride one'), rhetorical questions ('why do "
            "I always…'), third-person observations ('my Garmin judging me silently'). Do NOT "
            "start with 'told myself' or 'me telling myself' — that opening is overused.\n"
            + (("DO NOT reuse the structure or opening words of these recent lines:\n- "
                + "\n- ".join(recent) + "\n") if recent else "")
            + "\nOutput EXACTLY these labelled blocks:\n\n"
            "ONSCREEN: <the ONE on-screen text line that holds the whole clip — first-person, "
            "relatable, max ~12 words. This is the whole joke/hook. Plain text only — NO "
            "meta-labels like 'narrator:', 'me:', 'pov:', 'caption:'.>\n"
            "PUNCHLINE: <optional short payoff, or '-' if none. max ~8 words. Plain first-person "
            "text — NO 'narrator:', NO 'me:', NO meta-commentary labels, no stage-direction "
            "clichés. Just the punchline itself.>\n"
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


def _strip_meta(s: str) -> str:
    """Remove cheap meme meta-labels the model sometimes prepends (e.g. 'narrator:',
    'me:', 'pov:') so the on-screen text stays clean first-person copy."""
    return re.sub(r"^\s*(narrator|me|pov|caption|text|voiceover|vo)\s*[:\-–]\s*",
                  "", (s or "").strip(), flags=re.IGNORECASE).strip()


def _extract(label: str, text: str) -> str:
    m = re.search(rf"{label}:\s*(.+?)(?:\n[A-Z_]+:|\Z)", text, re.S)
    if not m:
        return ""
    # Strip stray template markers the model sometimes echoes (e.g. "<...>", quotes).
    out = m.group(1).strip().strip("<>").strip().strip('"').strip()
    # No AI em-dashes anywhere in reel text (on-screen, punchline, caption, YT meta).
    out = re.sub(r"\s*—\s*", ", ", out)      # em-dash → comma
    out = re.sub(r"\s+–\s+", ", ", out)      # spaced en-dash → comma (keep '10–20' ranges)
    out = re.sub(r",\s*,", ", ", out)        # tidy any double comma
    return out.strip()


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


def _drive_folder_urls(folder_id: str, mime: str) -> list:
    """Auto-discovery: list a Drive folder (GDRIVE_CLIPS/MUSIC_FOLDER_ID) and return
    public download URLs, so newly uploaded files are used automatically. Needs the
    Drive token minted with 'drive.metadata.readonly'. [] → callers use the *.json."""
    if not folder_id:
        return []
    try:
        import drive_upload
        files = drive_upload.list_folder_files(folder_id, mime=mime)
        return [f"https://drive.google.com/uc?export=download&id={f['id']}" for f in files]
    except Exception as e:
        print(f"   ⚠️  Drive auto-discovery skipped: {e}")
        return []


def _library_urls(folder_env: str, mime: str, json_name: str) -> tuple:
    """Return (urls, source_label). Prefer the Drive folder (auto-discovery); fall
    back to the committed *.json list."""
    folder = os.getenv(folder_env, "").strip()
    urls = _drive_folder_urls(folder, mime)
    if urls:
        return urls, f"Drive folder ({len(urls)})"
    try:
        items = json.load(open(os.path.join(BASE, json_name)))
        urls = [i.get("url") if isinstance(i, dict) else i for i in (items or [])]
        urls = [u for u in urls if u]
    except Exception:
        urls = []
    return urls, f"{json_name} ({len(urls)})"


def _pick_music() -> str:
    """Download today's license-free music track and return its local path.

    Source: the GDRIVE_MUSIC_FOLDER_ID Drive folder (auto-discovery) if set+authorized,
    else music_tracks.json. Instagram's own music library is NOT available via the API,
    so the track is baked into the video file. Use only license-free music. '' if none."""
    try:
        urls, src = _library_urls("GDRIVE_MUSIC_FOLDER_ID", "audio/", "music_tracks.json")
        if not urls:
            return ""
        url = urls[_slot_seed() % len(urls)]
        import caption_video
        dest = os.path.join(BASE, "output", "reels", "music_today")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if not caption_video.download(url, dest):   # Drive-robust (handles scan interstitial)
            print("   ⚠️  music download failed — reel wird ohne Musik erzeugt")
            return ""
        print(f"   ▶ music track from {src}")
        return dest
    except Exception as e:
        print(f"   ⚠️  music skipped: {e}")
        return ""


def _pick_vetted_clip() -> str:
    """Pick today's POV clip. Source: the GDRIVE_CLIPS_FOLDER_ID Drive folder
    (auto-discovery — drop a clip in, it's used automatically) if set+authorized, else
    reel_clips.json. Daily rotation. Same idea as doctor.running: reuse good POV footage,
    change only the caption. Returns "" if empty (then Higgsfield generation kicks in)."""
    urls, src = _library_urls("GDRIVE_CLIPS_FOLDER_ID", "video/", "reel_clips.json")
    if urls:
        pick = urls[_slot_seed() % len(urls)]
        print(f"   ▶ using vetted clip from {src}")
        return pick
    return ""


def _pick_start_image() -> str:
    """The start frame MUST be a POV road-ahead shot (pov_images.json) — animating a
    candid rider photo is what produced the morphing 'glidging' clips. Only fall back
    to the candid pool as a last resort, and warn loudly so POV images get generated."""
    try:
        pov = json.load(open(os.path.join(BASE, "pov_images.json")))
        if isinstance(pov, list) and pov:
            return pov[_slot_seed() % len(pov)]
    except Exception:
        pass
    print("   ⚠️  no pov_images.json — falling back to a candid photo (will look off). "
          "Run `python3 generate_pov_images.py` to build the POV road-ahead library.")
    return _IMAGE_POOL[_slot_seed() % len(_IMAGE_POOL)]


def main():
    # One post per slot (morning/noon/evening): skip if this slot already posted today
    # (saves credits + tokens). Dry-runs don't record, so testing stays unaffected.
    slot = _current_slot()[0]
    if _already_posted_slot():
        print(f"   ▶ reel skip — {slot} slot already posted today ({TODAY}). REEL_FORCE=1 to override.")
        return
    print(f"   ▶ reel slot: {slot}")

    topic = _todays_topic()
    try:
        brief = build_brief(topic)
    except Exception as e:
        print(f"   ⚠️  reel brief generation failed: {e}")
        mailer.send_email(f"⚠️ Velluto Reel PROBLEM — {TODAY}",
                          f"Reel-Text-Generierung fehlgeschlagen:\n\n{e}\n\n"
                          "(Meist ANTHROPIC_API_KEY-Problem.)")
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
        onscreen  = _strip_meta(_extract("ONSCREEN", brief))
        punchline = _strip_meta(_extract("PUNCHLINE", brief).strip(" -•\t"))
        if punchline in ("-", ""):
            punchline = ""
        _remember_line(onscreen)   # feed the no-repeat memory for future briefs
        out = os.path.join(BASE, "output", "reels", f"reel_{TODAY}.mp4")
        music = _pick_music()   # license-free track baked into the file (no IG music API)
        captioned = caption_video.download_and_caption(
            video_url, onscreen, punchline, out, duration=REEL_SECONDS, music_path=music)
        # captions_burned is True only if the returned file is the captioned one
        # (caption_video returns the *_raw.mp4 path on ffmpeg/font failure).
        captions_burned = bool(captioned) and not captioned.endswith("_raw.mp4")

    video_line = (f"🎬 Reel-Video (Quelle): {video_url}" if video_url
                  else "🎬 Reel-Video: kein Clip verfügbar (Drive-Ordner / reel_clips.json leer?).")
    if captioned and captions_burned:
        video_line += f"\n🎬 Mit Text-Overlay (auf VPS): {captioned}"
    elif video_url and not captions_burned:
        video_line += ("\n⚠️  TEXT-OVERLAY FEHLT — ffmpeg nicht gefunden. Fast immer: der Job lief "
                       "OHNE venv. Immer über `run_reel.sh` (aktiviert venv) laufen lassen, oder "
                       "`pip install imageio-ffmpeg` auch ins System-Python.")

    # Collect problems; we email ONLY if something actually went wrong (see bottom).
    problems = []
    if not video_url:
        problems.append("Kein Clip gefunden/erzeugt (Drive-Ordner / reel_clips.json leer?).")
    if video_url and not captions_burned:
        problems.append("Text-Overlay konnte nicht eingebrannt werden (ffmpeg-Problem auf dem VPS).")

    # ── Auto-post to Instagram (Graph API). Only posts when IG creds AND IG_AUTOPOST=1
    # are set; DRY-RUN / missing token are intentional states, NOT problems.
    post_line = "📮 Instagram: TEST-MODE (kein Auto-Posting)."
    allow_no_caption = os.getenv("REEL_ALLOW_NO_CAPTION", "").strip() in ("1", "true", "yes", "on")
    if video_url and not captions_burned and not allow_no_caption:
        post_line = "📮 Instagram: ⛔ nicht gepostet — Text-Overlay fehlt (ffmpeg installieren)."
    elif video_url:
        import instagram_post
        if instagram_post.is_configured():
            # Always: one-line, relatable caption + the four fixed hashtags.
            line = " ".join(_extract("CAPTION", brief).split())   # collapse to a single line
            ig_caption = f"{line}\n\n{HASHTAGS}".strip()
            public_url = ""
            if captioned and os.path.isfile(captioned):
                import drive_upload
                public_url = drive_upload.upload_public(captioned, name=f"velluto_reel_{TODAY}.mp4")
            if not public_url:
                # Never post the caption-less source clip — flag it instead.
                post_line = "📮 Instagram: ⛔ nicht gepostet — Drive-Upload fehlgeschlagen."
                if instagram_post.autopost_enabled():
                    problems.append("Drive-Upload des captionierten Reels fehlgeschlagen — nicht gepostet.")
            else:
                media_id = instagram_post.publish_reel(public_url, ig_caption)
                if media_id:
                    _record_post(media_id)
                    mode = "Test-Reel (nur Nicht-Follower)" if instagram_post.trial_enabled() else "Reel"
                    post_line = f"📮 Instagram: ✅ als {mode} gepostet (media id {media_id})"
                elif instagram_post.autopost_enabled():
                    post_line = "📮 Instagram: ⚠️ Posting fehlgeschlagen — siehe VPS-Log."
                    problems.append("Instagram-Posting fehlgeschlagen — siehe VPS-Log.")
                else:
                    post_line = "📮 Instagram: DRY-RUN (IG_AUTOPOST≠1)."
        else:
            post_line = "📮 Instagram: Token fehlt (instagram_auth.py) — nur Test-Mode."

    # ── Cross-post the SAME captioned reel to YouTube Shorts — search surface #2,
    # heavily cited by AI answers. Independent of IG; soft + dry-run unless
    # YT_AUTOPOST=1. Never breaks the reel run.
    yt_line = ""
    if captioned and os.path.isfile(captioned) and captions_burned:
        try:
            import youtube_short
            os_txt   = _strip_meta(_extract("ONSCREEN", brief))
            punch    = _strip_meta(_extract("PUNCHLINE", brief).strip(" -•\t"))
            cap_line = " ".join(_extract("CAPTION", brief).split())
            title, desc, tags = youtube_short.build_metadata(os_txt, punch, cap_line)
            vid = youtube_short.upload_short(captioned, title, desc, tags)
            if vid:
                yt_line = f"▶️ YouTube Short: ✅ https://youtu.be/{vid}"
            elif youtube_short.autopost_enabled() and youtube_short.is_configured():
                yt_line = "▶️ YouTube: ⚠️ Upload fehlgeschlagen — siehe VPS-Log."
                problems.append("YouTube-Short-Upload fehlgeschlagen — siehe VPS-Log.")
            elif youtube_short.is_configured():
                yt_line = "▶️ YouTube: DRY-RUN (YT_AUTOPOST≠1)."
            else:
                yt_line = "▶️ YouTube: nicht konfiguriert (youtube_auth.py)."
        except Exception as e:
            print(f"   ⚠️  YouTube cross-post skipped: {e}")

    # Email ONLY when something is broken. A clean run (incl. successful post) is silent —
    # you asked to be notified only when something doesn't work.
    if problems:
        body = (
            f"⚠️ Velluto Reel — Problem am {TODAY}:\n\n- " + "\n- ".join(problems) + "\n\n"
            f"Quelle: {topic.get('title') or topic.get('topic')}\n"
            f"{video_line}\n{post_line}\n{yt_line}\n"
            "────────────────────────────────────────\n\n"
            f"{brief}\n"
        )
        attach = [captioned] if (captioned and os.path.isfile(captioned)) else None
        mailer.send_email(f"⚠️ Velluto Reel PROBLEM — {TODAY}", body, attachments=attach)
    else:
        print(f"   ✔ reel ok ({post_line.strip()}) — keine E-Mail (nur Probleme werden gemailt).")


if __name__ == "__main__":
    main()
