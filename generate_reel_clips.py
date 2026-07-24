#!/usr/bin/env python3
"""
Build a DIVERSE library of faceless POV road-cycling reel clips via Higgsfield,
appended to reel_clips.json — the vetted-clip pool the Reel automation rotates
through (instagram_reel_brief._pick_vetted_clip). Solves the "only 1 clip → every
reel looks the same" problem: 10 hand-crafted scenes, each a different setting /
light / weather / speed, so the daily reel actually varies.

Each clip is built in two steps (Higgsfield DoP is image-to-video, not text-to-video):
  1. Higgsfield Soul renders a fresh POV road-ahead START IMAGE for the scene.
  2. Higgsfield DoP animates that still into a ~14 s 9:16 clip with a matched motion.
The finished video URLs are appended to reel_clips.json as {url, desc}; the start
images are also appended to pov_images.json so the on-the-fly fallback gets more
variety too.

Run on the VPS (creds live in .env there — this consumes Higgsfield credits):
  python3 generate_reel_clips.py            # generate 10 + APPEND to reel_clips.json
  python3 generate_reel_clips.py --fresh    # start reel_clips.json from scratch
  python3 generate_reel_clips.py --only 1,4,9   # regenerate just those scene numbers
  python3 generate_reel_clips.py --dry-run  # print the scenes/prompts, spend nothing

Cost note: 10 images + 10 videos in one batch. Deliberate, not per-reel — the reel
job then just reuses these, changing only the caption. ~1 credit-heavy run buys weeks
of varied reels.
"""
from __future__ import annotations

import json
import os
import sys

import higgsfield_image
import higgsfield_video

BASE = os.path.dirname(os.path.abspath(__file__))
CLIPS = os.path.join(BASE, "reel_clips.json")
POV   = os.path.join(BASE, "pov_images.json")
DURATION = 14   # match instagram_reel_brief.REEL_SECONDS so no re-cut/loop is needed

# Shared POV framing — identical to generate_pov_images.py so every start frame
# unmistakably reads as ROAD CYCLING (drop bars + Garmin + tarmac ahead, faceless).
# The hard negatives kill the car/desert/gravel/rider-visible failure modes.
_FG  = ("first-person POV of a road cyclist: black drop handlebars with brake hoods and a "
        "Garmin bike computer in the lower foreground, the front wheel on smooth grey asphalt")
_NEG = ("shot on a GoPro action camera, photorealistic, sharp, natural lighting. "
        "NO car, NO motorbike, NO dashboard, NO windshield, NO desert, NO gravel, NO dirt trail, "
        "NO off-road, NO hands, NO phone, NO rider visible, NO people, no text, no logo. Vertical 9:16")

# Motion cues shared by all clips, then specialised per scene (climb = steady grind,
# descent = fast rush, cruise = gentle sway). Faceless, camera-forward, no morphing.
_MOVE = ("smooth first-person forward motion, the road rushing gently toward the camera, "
         "subtle natural handlebar sway, stable horizon, no warping, no people appearing")

# 10 diverse scenes: setting × light × weather × speed. Each entry is
# (image scene fragment, motion specialisation, human-readable desc).
SCENES = [
    ("an empty sunlit alpine tarmac road with switchbacks dropping away ahead, golden hour",
     "steady climbing cadence, unhurried pace up the gradient",
     "POV Alpen-Serpentinen-Anstieg, goldene Stunde"),
    ("a smooth paved forest road ahead at sunrise, dappled light through pine trees",
     "relaxed cruising pace, light flickering through the trees",
     "POV Waldstraße bei Sonnenaufgang, Lichtspiel"),
    ("a winding paved coastal road ahead at sunset, ocean glinting beside the road, warm light",
     "flowing cruise, gentle lean into a sweeping bend along the coast",
     "POV Küstenstraße bei Sonnenuntergang, Meerblick"),
    ("an open paved country road ahead through green fields, blue sky, sunny morning",
     "steady tempo pace on the flat, wide open road",
     "POV offene Landstraße, grüne Felder, Vormittag"),
    ("a steep paved Dolomites switchback rising ahead between pale limestone walls, dramatic sky",
     "slow grinding climb, effortful steady rhythm up the ramp",
     "POV Dolomiten-Kehre, Kalksteinwände"),
    ("quiet paved city streets ahead at dawn, wet asphalt reflections, soft light, empty road",
     "flowing pace through empty streets, reflections sliding past",
     "POV leere Stadt bei Morgengrauen, nasser Asphalt"),
    ("rolling green countryside with the tarmac road rising and dipping ahead, patchwork fields",
     "rhythmic cruising, road cresting a rise then dipping away",
     "POV hügelige Landschaft, Feldermosaik"),
    ("a paved forest road ahead in light rain, fine water droplets on the lens, moody atmosphere",
     "cautious steady pace, rain misting the air, calm and moody",
     "POV Waldstraße im Nieselregen, Tropfen auf der Linse"),
    ("a long flat paved road ahead through golden farmland, summer heat haze shimmering",
     "fast steady pace on the flat, heat shimmer rippling on the tarmac ahead",
     "POV goldene Felder, Sommer-Hitzeflimmern"),
    ("a fast descent on a paved road through autumn trees ahead, orange leaves falling, tunnel of colour",
     "quick descent, real sense of speed, edges of the frame streaking past, leaves swirling",
     "POV Herbst-Abfahrt, fallende Blätter, Speed"),
]


def _load(path):
    try:
        data = json.load(open(path))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _parse_only(argv):
    """--only 1,4,9 → {0,3,8} (1-based scene numbers to 0-based indices)."""
    if "--only" not in argv:
        return None
    try:
        raw = argv[argv.index("--only") + 1]
        return {int(x) - 1 for x in raw.replace(" ", "").split(",") if x}
    except Exception:
        print("   ⚠️  --only expects e.g. --only 1,4,9 — ignoring")
        return None


def main():
    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    fresh = "--fresh" in argv
    only = _parse_only(argv)

    picks = [(i, s) for i, s in enumerate(SCENES) if only is None or i in only]

    print(f"🎬 Generating {len(picks)} diverse POV road-cycling reel clip(s) via Higgsfield")
    print(f"   ({'DRY-RUN — nothing spent' if dry else 'this consumes Higgsfield credits'})\n")

    if dry:
        for i, (scene, move, desc) in picks:
            print(f"[{i+1}] {desc}")
            print(f"     IMG:   {_FG}, {scene}, {_NEG}")
            print(f"     MOTION:{_MOVE}, {move}\n")
        print("Dry-run only. Re-run without --dry-run on the VPS to generate.")
        return

    new_clips, new_imgs = [], []
    for i, (scene, move, desc) in picks:
        n = i + 1
        print(f"[{n}/{len(SCENES)}] {desc}")
        img_prompt = f"{_FG}, {scene}, {_NEG}"
        img = higgsfield_image.generate_image(img_prompt, aspect_ratio="9:16")
        if not img:
            print("     ✗ start image failed — skipping this scene\n")
            continue
        new_imgs.append(img)
        motion = f"{_MOVE}, {move}"
        vid = higgsfield_video.generate_video(
            motion, image_url=img, duration=DURATION, aspect_ratio="9:16")
        if not vid:
            print("     ✗ video animation failed — skipping this scene\n")
            continue
        new_clips.append({"url": vid, "desc": desc})
        print(f"     ✓ clip ready\n")

    # ── persist. reel_clips.json: append (keep Leopold's own clip) unless --fresh.
    clips = [] if fresh else _load(CLIPS)
    seen = {c.get("url") for c in clips if isinstance(c, dict)}
    clips += [c for c in new_clips if c["url"] not in seen]
    json.dump(clips, open(CLIPS, "w"), indent=2, ensure_ascii=False)

    # pov_images.json: append the fresh start frames so the on-the-fly fallback varies too.
    imgs = _load(POV)
    imgs += [u for u in new_imgs if u not in imgs]
    json.dump(list(dict.fromkeys(imgs)), open(POV, "w"), indent=2)

    print(f"✓ {len(new_clips)}/{len(picks)} clip(s) generated")
    print(f"  reel_clips.json now holds {len(clips)} clip(s) → the reel automation rotates through them")
    print(f"  pov_images.json now holds {len(imgs)} POV start image(s)")
    if not new_clips:
        print("  (none generated — check HIGGSFIELD_API_KEY/SECRET and the errors above)")


if __name__ == "__main__":
    main()
