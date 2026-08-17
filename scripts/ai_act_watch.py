#!/usr/bin/env python3
"""
Weekly watch on our AI-media exposure under Art. 50 AI Act / § 5a UWG.

WHAT IT WATCHES — AND WHAT IT CANNOT
It watches OUR surfaces, not the law. No script can tell you that a court has
read "matters of public interest" more broadly than we assumed; that needs a
person reading legal news. What it can do is catch the thing that actually
changes our exposure from one week to the next: a generation path being switched
on.

Today the two riskiest paths are off — publishing_rules.yml has images.generate
false and reels.enabled false — so the only live AI media is whatever sits in the
cover pool. The moment either flag flips, we start publishing fresh AI imagery to
an audience, and Art. 50(4) applies to material that appears authentic. That flip
is one line in a config file and would otherwise be silent. This makes it loud.

WHY IMAGES AND NOT ARTICLE TEXT
Art. 50(4) subpara 2 covers AI text published to inform the public on matters of
public interest. Buying guides for cycling sunglasses are commercial content, so
the blog most likely sits outside it — and by decision of 2026-08-17 the text
stays unlabelled for now, watched rather than changed. Images are different:
subpara 1 covers image content that appears authentic regardless of subject
matter, and § 5a UWG applies to a photorealistic AI image suggesting a real
riding situation whatever the AI Act says.

STATES
  OK       nothing published that needs a disclosure
  WATCH    unclassified pool images — exposure unknown, not zero
  ACTION   AI media live without disclosure, or a generation path switched on

Usage:
  python3 scripts/ai_act_watch.py            # gated weekly
  python3 scripts/ai_act_watch.py --force
"""
import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HISTORY = os.path.join(ROOT, "data", "ai_act_watch.json")
RULES = os.path.join(ROOT, "config", "publishing_rules.yml")
GATE_DAYS = 7

# Art. 50 AI Act transparency obligations have applied since this date. Kept as a
# constant so the report can state plainly that we are inside the period, rather
# than describing a deadline that has already passed.
IN_FORCE = dt.date(2026, 8, 2)


def _rules() -> dict:
    try:
        import yaml
        with open(RULES, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"   ⚠️  publishing_rules.yml nicht lesbar: {e}")
        return {}


def check() -> list[tuple[str, str, str]]:
    """[(state, topic, note)] — every finding, most severe first."""
    out = []
    rules = _rules()
    gen_images = bool((rules.get("images") or {}).get("generate"))
    reels_on = bool((rules.get("reels") or {}).get("enabled"))

    try:
        from ai_image_scan import ai_keys, unknown_keys
        known_ai, unknown = ai_keys(), unknown_keys()
        scanned = True
    except Exception:
        known_ai, unknown, scanned = [], [], False

    if not scanned or (not known_ai and not unknown):
        out.append(("WATCH", "Bild-Inventar",
                    "data/ai_media_inventory.json fehlt oder ist leer — die Herkunft der "
                    "Pool-Bilder ist unbekannt. `python3 scripts/ai_image_scan.py`"))
    else:
        if known_ai:
            # Whether they are still in WHITELIST decides which half of the job is
            # left. Removing them stops new articles; it does nothing for the ones
            # already published, and those are what the public sees.
            try:
                from ai_image_scan import whitelist
                still_pooled = sorted(set(known_ai) & set(whitelist()))
            except Exception:
                still_pooled = []
            if still_pooled:
                out.append(("ACTION", "KI-Bilder im Pool",
                            f"{len(still_pooled)} belegt KI-generierte Bild(er) stehen noch in "
                            f"seo_bot.WHITELIST: {', '.join(still_pooled[:4])}"
                            f"{' …' if len(still_pooled) > 4 else ''}. Art. 50 Abs. 4 AI Act "
                            "und § 5a UWG — entfernen oder kennzeichnen."))
            else:
                out.append(("WATCH", "Veröffentlichte Cover",
                            f"{len(known_ai)} KI-Bild(er) sind aus dem Pool entfernt — das gilt "
                            "aber nur für neue Artikel. Ob bereits veröffentlichte sie noch als "
                            "Cover tragen, prüft `python3 scripts/replace_ai_covers.py` "
                            "(Probelauf, schreibt nichts)."))
        if unknown:
            out.append(("WATCH", "Bilder ohne Einordnung",
                        f"{len(unknown)} Pool-Bild(er) ohne Metadaten — Shopify entfernt sie "
                        f"beim Recodieren, das ist also keine Entwarnung. Einordnen mit "
                        f"`scripts/ai_image_scan.py --set {unknown[0]}=ai|photo`"))

    if gen_images:
        out.append(("ACTION", "KI-Coverbilder aktiv",
                    "publishing_rules.yml images.generate steht auf true — jeder neue Artikel "
                    "bekommt ein frisch erzeugtes KI-Cover. Ohne Kennzeichnung ist das die "
                    "direkteste Art-50-Abs.-4-Exposition, die wir uns bauen können."))
    if reels_on:
        out.append(("ACTION", "Reel-Automation aktiv",
                    "publishing_rules.yml reels.enabled steht auf true — KI-Video an ein "
                    "Publikum, 3×/täglich. Art. 50 Abs. 4 UAbs. 1 verlangt hier die "
                    "Offenlegung; Instagram erwartet zusätzlich das eigene KI-Label."))
    if not gen_images and not reels_on:
        out.append(("OK", "Erzeugungspfade",
                    "images.generate und reels.enabled sind aus — es entsteht derzeit keine "
                    "neue KI-Medienausgabe."))

    out.append(("OK", "Artikeltext",
                "bewusst unmarkiert: Kaufberatung ist kommerzieller Inhalt, nicht "
                "'Angelegenheit von öffentlichem Interesse' (Art. 50 Abs. 4 UAbs. 2). "
                "Entscheidung vom 2026-08-17, vorerst nur beobachten."))

    order = {"ACTION": 0, "WATCH": 1, "OK": 2}
    return sorted(out, key=lambda r: order[r[0]])


def main() -> None:
    hist = []
    try:
        with open(HISTORY, encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        pass
    if "--force" not in sys.argv and hist:
        try:
            last = dt.date.fromisoformat(hist[-1]["date"])
            if (dt.date.today() - last).days < GATE_DAYS:
                print("   AI-Act-Wächter: geprüft vor <7 Tagen — nichts zu tun")
                return
        except Exception:
            pass

    days = (dt.date.today() - IN_FORCE).days
    period = (f"seit {days} Tagen in Kraft" if days >= 0
              else f"gilt ab {IN_FORCE.isoformat()} (in {-days} Tagen)")
    print(f"⚖️  AI Act Art. 50 — {period}\n")

    findings = check()
    for state, topic, note in findings:
        icon = {"ACTION": "⛔", "WATCH": "⚠️ ", "OK": "✅"}[state]
        print(f"  {icon} {state:6} {topic}")
        print(f"     {note}\n")

    entry = {"date": dt.date.today().isoformat(),
             "findings": [{"state": s, "topic": t, "note": n}
                          for s, t, n in findings if s != "OK"]}
    hist.append(entry)
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(hist[-52:], f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
