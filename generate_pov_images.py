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

# Photorealistic ROAD-CYCLING POV. The key to reading as *road cycling* (not a car,
# not hiking): the road bike's black DROP HANDLEBARS + a Garmin bike computer must be
# clearly in the lower foreground, with the front wheel rolling on SMOOTH TARMAC ahead.
# Hands not visible. Hard negatives kill the car/desert/gravel failure modes we saw.
_FG  = ("first-person POV of a road cyclist: black drop handlebars with brake hoods and a "
        "Garmin bike computer in the lower foreground, the front wheel on smooth grey asphalt")
_NEG = ("shot on a GoPro action camera, photorealistic, sharp, natural lighting. "
        "NO car, NO motorbike, NO dashboard, NO windshield, NO desert, NO gravel, NO dirt trail, "
        "NO off-road, NO hands, NO phone, NO rider visible, NO people, no text, no logo. Vertical 9:16")
PROMPTS = [
    f"{_FG}, an empty sunlit alpine tarmac mountain road with switchbacks dropping away ahead, golden hour, {_NEG}",
    f"{_FG}, a smooth paved forest road ahead at sunrise, dappled light through pine trees, {_NEG}",
    f"{_FG}, a winding paved coastal road ahead at sunset, ocean glinting beside the road, warm light, {_NEG}",
    f"{_FG}, an open paved country road ahead through green fields, blue sky, sunny morning, {_NEG}",
    f"{_FG}, a steep paved Dolomites switchback rising ahead between limestone walls, dramatic, {_NEG}",
    f"{_FG}, quiet paved city streets ahead at dawn, wet asphalt reflections, soft light, {_NEG}",
    f"{_FG}, rolling green countryside with the tarmac road ahead, blue sky and fields, {_NEG}",
    f"{_FG}, a paved forest road ahead in light rain, water droplets on the lens, moody atmosphere, {_NEG}",
    f"{_FG}, a long flat paved road ahead through golden farmland, summer haze, {_NEG}",
    f"{_FG}, descending fast on a paved road through autumn trees ahead, falling leaves, sense of speed, {_NEG}",
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
