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

# Photorealistic, vertical, organic POV road-cycling scenes — no text, no branding.
PROMPTS = [
    "POV from a road cyclist's handlebars descending a sunlit alpine mountain pass, hands on the drops, slight speed blur, golden hour, photorealistic action-cam look, vertical",
    "POV helmet-cam of a road cyclist riding a misty forest gravel road at sunrise, dappled light through trees, photorealistic, vertical",
    "POV from the saddle on a winding coastal road at sunset, ocean on one side, warm light, realistic phone photo, vertical",
    "POV riding inside a tight group of road cyclists, wheels close together, motion and speed, photorealistic, vertical",
    "POV of a cyclist grinding up a steep Dolomites switchback, effort, dramatic limestone peaks, photorealistic, vertical",
    "POV through empty city streets at dawn on a road bike, wet asphalt reflections, soft urban light, photorealistic, vertical",
    "POV handlebar view on a rolling countryside road, green fields and blue sky, a bike computer faintly in frame, photorealistic, vertical",
    "POV of a road cyclist in light rain on a forest road, water droplets, moody atmospheric light, photorealistic, vertical",
    "POV gravel ride kicking up dust on a sunlit desert trail at midday, rugged landscape, photorealistic, vertical",
    "POV descending fast through autumn trees, falling leaves, sense of speed, realistic action-cam, vertical",
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
