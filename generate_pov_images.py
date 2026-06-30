#!/usr/bin/env python3
"""
Build a library of original POV road-cycling images via Higgsfield Soul, saved to
pov_images.json. The Reel generator then rotates through these as start frames —
fully organic, no logo, no branded look.

Run once (regenerate whenever you want fresh shots):
  python3 generate_pov_images.py          # fresh library (overwrites)
  python3 generate_pov_images.py --add     # append to the existing library

Each image consumes Higgsfield credits, so it's a deliberate batch, not per-reel.
"""
import json
import os
import sys

import higgsfield_image

BASE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(BASE, "pov_images.json")

# Photorealistic POV road-cycling scenes. Framed to look like real GoPro/action-cam
# footage looking DOWN THE ROAD AHEAD — explicitly NO hands, no phone, no rider in
# frame, no people, to avoid the usual AI artifacts. No text, no branding.
_NEG = "shot on a GoPro action camera, photorealistic, natural lighting, no hands, no phone, no rider visible, no people, no text, vertical 9:16"
PROMPTS = [
    f"First-person handlebar POV looking down an empty sunlit alpine mountain road ahead, tarmac and switchbacks dropping away, golden hour, {_NEG}",
    f"POV looking forward along a misty forest gravel road at sunrise, dappled light through pine trees, {_NEG}",
    f"First-person view down a winding coastal road at sunset, ocean glinting beside the road, warm light, {_NEG}",
    f"POV on an open country road with a small group of road cyclists riding ahead in the distance, their backs and wheels in front, motion, {_NEG}",
    f"First-person POV climbing a steep Dolomites switchback, the road rising ahead between limestone walls, dramatic, {_NEG}",
    f"POV down quiet city streets at dawn, wet asphalt reflections, soft light, {_NEG}",
    f"First-person POV over rolling green countryside, road ahead, blue sky and fields, {_NEG}",
    f"POV looking ahead on a forest road in light rain, water droplets on the lens, moody atmosphere, {_NEG}",
    f"First-person POV on a dusty sunlit gravel desert trail, the track stretching ahead, rugged landscape, {_NEG}",
    f"POV descending fast through autumn trees, the road ahead, falling leaves, sense of speed, {_NEG}",
]


def main():
    urls = []
    if "--add" in sys.argv and os.path.exists(OUT):
        try:
            urls = json.load(open(OUT)) or []
        except Exception:
            urls = []

    print(f"Generating {len(PROMPTS)} POV images via Higgsfield Soul…\n")
    for i, p in enumerate(PROMPTS, 1):
        print(f"[{i}/{len(PROMPTS)}] {p[:65]}…")
        u = higgsfield_image.generate_image(p, aspect_ratio="9:16")
        if u:
            urls.append(u)

    urls = list(dict.fromkeys(u for u in urls if u))   # dedupe, drop empties
    json.dump(urls, open(OUT, "w"), indent=2)
    print(f"\n✓ {len(urls)} POV images saved to {OUT}")
    if not urls:
        print("  (none generated — check HIGGSFIELD_API_KEY/SECRET and the console errors above)")


if __name__ == "__main__":
    main()
