#!/usr/bin/env python3
"""
Which cover images are AI-generated? Scan the pool for provenance markers.

WHY THIS EXISTS
config/publishing_rules.yml:87 describes the cover pool as "Shopify-CDN photos +
Higgsfield lifestyle images" — mixed, and the filenames do not say which is which.
Since 2 August 2026 that distinction has legal weight: Art. 50(4) AI Act obliges
the DEPLOYER to disclose AI-generated image content that appears authentic, and
§ 5a UWG independently makes a photorealistic AI image that suggests a real riding
situation misleading by omission. Neither can be complied with while we do not
know which images they are.

higgsfield_image.py generates and uploads but keeps no record, so there is no
internal log to read. This reads the files themselves.

WHAT A RESULT MEANS
  AI       a generator signature was found — definitive
  PHOTO    camera EXIF (make/model/lens) and no generator marker — strong
  UNKNOWN  neither — INCONCLUSIVE, NOT an all-clear

UNKNOWN will be the common answer and that is expected: Shopify re-encodes
uploads to WebP and strips metadata in the process, so an AI image can arrive
here perfectly clean. A negative finding is therefore no evidence of camera
origin. Those entries need a human to classify them, which is what
data/ai_media_inventory.json is for — this scan seeds it, it does not settle it.

Writes data/ai_media_inventory.json: the single source of truth for every other
part of the repo that needs to know. Existing human classifications are never
overwritten by a re-scan.

Usage:
  python3 scripts/ai_image_scan.py                 # scan, write the inventory
  python3 scripts/ai_image_scan.py --show          # print the inventory, no network
  python3 scripts/ai_image_scan.py --set KEY=ai    # record a human classification
"""
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

INVENTORY = os.path.join(ROOT, "data", "ai_media_inventory.json")
VALID = ("ai", "photo", "unknown")

# Read far enough in to catch a metadata block without pulling whole images: EXIF
# and XMP sit near the front, C2PA manifests usually within the first blocks.
HEAD_BYTES = 262144

# A C2PA manifest is NOT evidence of AI. C2PA / Content Credentials is a neutral
# provenance container — Photoshop writes one on export, and so does a camera that
# supports it. Treating its mere presence as an AI signature was wrong; it happened
# to give the right answer on the first file inspected only because that file also
# carried the real marker. What decides it is the IPTC digitalSourceType inside the
# manifest, and the name of the software agent that made the image.
_AI_MARKERS = [
    (rb"trainedAlgorithmicMedia", "IPTC digitalSourceType: trainedAlgorithmicMedia"),
    (rb"compositeWithTrainedAlgorithmicMedia", "IPTC: Komposit mit KI-Anteil"),
    (rb"higgsfield", "Higgsfield"),
    (rb"gpt-image|dall-?e", "OpenAI gpt-image / DALL-E"),
    (rb"midjourney", "Midjourney"),
    (rb"stable\s?diffusion|stability\.ai|automatic1111|comfyui", "Stable Diffusion"),
    (rb"adobe\s?firefly", "Adobe Firefly"),
    (rb"imagen\b|black\s?forest\s?labs|flux\.1", "Imagen / FLUX"),
    (rb"runwayml|pika\s?labs|leonardo\.ai", "weiterer Generator"),
]

# Camera provenance. Present only in files that still carry original EXIF or a
# C2PA manifest asserting capture.
_CAM_MARKERS = [
    (rb"digitalCapture", "IPTC digitalSourceType: digitalCapture (Kamera)"),
    (rb"Canon|NIKON|SONY|FUJIFILM|Panasonic|OLYMPUS|Leica|Hasselblad|DJI", "Kamerahersteller"),
    (rb"FNumber|FocalLength|ISOSpeedRatings|ExposureTime", "EXIF-Aufnahmedaten"),
    (rb"Lightroom|Camera Raw|Capture One|Photo Mechanic", "RAW-Workflow"),
]

# Provenance data exists but says nothing about origin either way — worth naming
# separately, because "a manifest is present" invites the false conclusion that
# the question has been answered.
_PROVENANCE = rb"c2pa|jumbf|contentauth"


def _load() -> dict:
    try:
        with open(INVENTORY, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(inv: dict) -> None:
    os.makedirs(os.path.dirname(INVENTORY), exist_ok=True)
    with open(INVENTORY, "w", encoding="utf-8") as f:
        json.dump(inv, f, ensure_ascii=False, indent=1, sort_keys=True)


def _head(url: str) -> bytes:
    """First HEAD_BYTES of the file. Range request so we do not pull 60 full images."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Velluto-ai-scan/1.0", "Range": f"bytes=0-{HEAD_BYTES - 1}"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read(HEAD_BYTES)


def classify(blob: bytes) -> tuple[str, str]:
    """(verdict, evidence). AI wins over camera markers: a retouched AI image can
    carry both, and the generator signature is the one that was actually proven."""
    for pat, name in _AI_MARKERS:
        if re.search(pat, blob, re.I):
            return "ai", name
    for pat, name in _CAM_MARKERS:
        if re.search(pat, blob, re.I):
            return "photo", name
    if re.search(_PROVENANCE, blob, re.I):
        return "unknown", "C2PA-Manifest vorhanden, macht aber keine Herkunftsangabe"
    return "unknown", "keine Metadaten (Shopify entfernt sie beim WebP-Recodieren)"


def whitelist() -> dict:
    """Read seo_bot.WHITELIST without importing seo_bot.

    Importing it pulls in anthropic, shopify auth and the rest of the pipeline —
    a heavy chain for reading one dict literal, and it fails outright anywhere the
    full runtime is not installed. The literal is parsed instead, so this script
    runs from a bare checkout.
    """
    import ast
    src = open(os.path.join(ROOT, "seo_bot.py"), encoding="utf-8").read()
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "WHITELIST" for t in node.targets)):
            return ast.literal_eval(node.value)
    return {}


def scan() -> dict:
    WHITELIST = whitelist()
    if not WHITELIST:
        print("   ⚠️  WHITELIST in seo_bot.py nicht gefunden — nichts zu prüfen")
        return {}
    inv = _load()
    print(f"🔍 {len(WHITELIST)} Pool-Bilder werden geprüft (1 Anfrage/s)\n")
    counts = {"ai": 0, "photo": 0, "unknown": 0, "fehler": 0}
    for i, (key, url) in enumerate(sorted(WHITELIST.items())):
        prev = inv.get(key) or {}
        # A human classification is the better evidence and must survive a re-scan.
        if prev.get("source") == "human":
            counts[prev.get("verdict", "unknown")] = counts.get(prev.get("verdict", "unknown"), 0) + 1
            print(f"  ·  {key:32} {prev['verdict'].upper():8} (von Hand gesetzt)")
            continue
        if i:
            time.sleep(1.0)     # the sitemap check earned 429s by bursting; do not repeat it
        try:
            verdict, evidence = classify(_head(url))
        except Exception as e:
            counts["fehler"] += 1
            print(f"  ✗  {key:32} nicht lesbar: {str(e)[:48]}")
            continue
        counts[verdict] += 1
        icon = {"ai": "🤖", "photo": "📷", "unknown": "❓"}[verdict]
        print(f"  {icon}  {key:32} {verdict.upper():8} {evidence}")
        inv[key] = {"verdict": verdict, "evidence": evidence, "source": "scan", "url": url}
    _save(inv)

    print(f"\n── Ergebnis ──")
    print(f"  🤖 KI-generiert (belegt): {counts['ai']}")
    print(f"  📷 Kamera-Metadaten:      {counts['photo']}")
    print(f"  ❓ ohne Metadaten:        {counts['unknown']}")
    if counts["fehler"]:
        print(f"  ✗  nicht lesbar:          {counts['fehler']}")
    if counts["unknown"]:
        print(f"\n❓ ist KEINE Entwarnung — Shopify entfernt Metadaten beim Recodieren,")
        print(f"   ein KI-Bild kommt hier also sauber an. Diese {counts['unknown']} musst du einordnen:")
        print(f"     python3 scripts/ai_image_scan.py --set Lifestyle_1x1=ai")
    print(f"\nInventar: {os.path.relpath(INVENTORY, ROOT)}")
    return inv


def show() -> None:
    inv = _load()
    if not inv:
        print("Inventar ist leer — erst `python3 scripts/ai_image_scan.py` laufen lassen.")
        return
    for verdict in VALID:
        keys = sorted(k for k, v in inv.items() if v.get("verdict") == verdict)
        if not keys:
            continue
        icon = {"ai": "🤖", "photo": "📷", "unknown": "❓"}[verdict]
        print(f"\n{icon} {verdict.upper()} ({len(keys)})")
        for k in keys:
            src = inv[k].get("source", "scan")
            print(f"   {k:34} {'✋ von Hand' if src == 'human' else inv[k].get('evidence', '')[:52]}")


def set_verdicts(pairs: list[str]) -> None:
    """A human classification outranks the scan and is never overwritten by it."""
    inv = _load()
    for pair in pairs:
        if "=" not in pair:
            print(f"   ⚠️  '{pair}' übersprungen — erwartet KEY=ai|photo|unknown")
            continue
        key, _, verdict = pair.partition("=")
        key, verdict = key.strip(), verdict.strip().lower()
        if verdict not in VALID:
            print(f"   ⚠️  '{verdict}' ist keine gültige Einordnung ({'|'.join(VALID)})")
            continue
        inv[key] = {**inv.get(key, {}), "verdict": verdict,
                    "evidence": "von Hand eingeordnet", "source": "human"}
        print(f"   ✓ {key} → {verdict.upper()}")
    _save(inv)


def ai_keys() -> list[str]:
    """Pool keys known to be AI-generated. Read by the AI Act watchdog."""
    return sorted(k for k, v in _load().items() if v.get("verdict") == "ai")


def unknown_keys() -> list[str]:
    return sorted(k for k, v in _load().items() if v.get("verdict") == "unknown")


def main() -> None:
    if "--show" in sys.argv:
        show()
    elif "--set" in sys.argv:
        set_verdicts(sys.argv[sys.argv.index("--set") + 1:])
    else:
        scan()


if __name__ == "__main__":
    main()
