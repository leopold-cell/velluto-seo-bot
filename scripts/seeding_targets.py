#!/usr/bin/env python3
"""
Seeding / outreach target finder — turns the bot's existing SEO intelligence
into a prioritized product-seeding list (the off-page lever that moves you from
page-1-bottom to top-3).

The bot already knows who owns your money keywords: it ranks SERPs, tracks who
Google AI Overviews + Perplexity cite, and holds a 320-entry competitor
registry. This aggregates all of that into: for each money keyword, WHO ranks /
is AI-cited, classified into who's worth seeding a free StradaPro to (editorial
reviewers, YouTubers, Reddit) vs. stockist outreach (retailers) vs. skip
(competitor brands / own domain).

Priority logic (highest first):
  1. Cited by Google AI / Perplexity but Velluto NOT in that answer → seeding
     these gets you INTO the AI answer set (pure GEO gain).
  2. Ranks top-3 for a money keyword → high domain authority + audience.
  3. Appears across many money keywords → category authority.
  YouTube (video/GEO) and Reddit (AI cites it constantly) get a type bump.

Reads (all best-effort, generated on the VPS by the daily/weekly jobs):
  data/processed/serp_snapshots.json  (organic per keyword/market)
  data/processed/ai_overview_snapshots.json  (AI Overview citations)
  data/perplexity_geo.json  (Perplexity citations, per market)
  competitors_discovered.json  (domain → name)
Writes: data/seeding_targets.json  (for the influencer dashboard) + emails a
weekly digest. Self-gated to 7 days (runs as a daily run.sh step).

Usage:
  python3 scripts/seeding_targets.py            # gated weekly
  python3 scripts/seeding_targets.py --force
"""
import datetime as dt
import json
import os
import re
import sys
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OUT   = os.path.join(ROOT, "data", "seeding_targets.json")
STATE = os.path.join(ROOT, "data", "seeding_targets_state.json")
OWN   = "velluto-shop.com"

# Retailers / marketplaces — stockist-outreach track, not editorial seeding.
RETAILERS = ("amazon.", "decathlon.", "bike24", "bike-discount", "wiggle",
             "chainreactioncycles", "rosebikes", "rose-bikes", "bergfreunde",
             "bergzeit", "misterspex", "fielmann", "idealo", "ebay.", "alltricks",
             "probikeshop", "kleinanzeigen", "otto.", "galaxus", "smec", "shopping24")
# Eyewear brands — they won't review a competitor. Skip from seeding.
BRANDS = ("oakley", "sungod", "roka", "100percent", "rudyproject", "rudy-project",
          "poc-sports", "julbo", "bolle", "koo.", "sciconsports", "scicon",
          "alba-optics", "tifosi", "goodr", "shadyrays", "smithoptics", "uvex",
          "adidas", "evileye", "endurasport", "sportful", "ekoi", "van-rysel",
          "lankeleisi", "blenderseyewear", "demonsun")


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _domain(item: dict) -> str:
    d = (item.get("domain") or "").lower().lstrip("www.")
    if not d:
        u = item.get("url") or ""
        d = urlparse(u).netloc.lower().lstrip("www.") if u else ""
    return d


def classify(domain: str) -> str:
    if not domain or OWN in domain:
        return "own"
    if "youtube.com" in domain or "youtu.be" in domain:
        return "youtube"
    if "reddit.com" in domain:
        return "reddit"
    if any(r in domain for r in RETAILERS):
        return "retailer"
    if any(b in domain for b in BRANDS):
        return "brand"
    return "editorial"


def gate_ok(force: bool) -> bool:
    if force:
        return True
    last = _load(STATE, {}).get("last_run")
    if not last:
        return True
    try:
        return (dt.date.today() - dt.date.fromisoformat(last)).days >= 7
    except Exception:
        return True


def build() -> dict:
    serp = _load(os.path.join(ROOT, "data", "processed", "serp_snapshots.json"), {})
    aio  = _load(os.path.join(ROOT, "data", "processed", "ai_overview_snapshots.json"), {})
    ppx  = _load(os.path.join(ROOT, "data", "perplexity_geo.json"), [])
    registry = _load(os.path.join(ROOT, "competitors_discovered.json"), {})

    targets: dict[str, dict] = {}

    def _t(domain: str) -> dict:
        return targets.setdefault(domain, {
            "domain": domain, "type": classify(domain), "name": registry.get(domain, ""),
            "keywords": set(), "best_rank": 99, "ai_cited": 0,
            "ai_cited_velluto_absent": 0, "score": 0})

    # 1) Organic SERP → who ranks for our money keywords
    for snap in (serp.get("snapshots") or []):
        kw = snap.get("keyword", "")
        for it in (snap.get("organic") or [])[:10]:
            d = _domain(it)
            if not d:
                continue
            t = _t(d)
            t["keywords"].add(kw)
            t["best_rank"] = min(t["best_rank"], int(it.get("rank_group") or it.get("rank_absolute") or 99))

    # 2) Google AI Overview citations
    for a in (aio.get("ai_overviews") or []):
        v_absent = not a.get("velluto_cited")
        for c in (a.get("cited_sources") or []):
            d = (c.get("domain") or "").lower().lstrip("www.")
            if not d:
                continue
            t = _t(d)
            t["ai_cited"] += 1
            if v_absent:
                t["ai_cited_velluto_absent"] += 1
            if a.get("keyword"):
                t["keywords"].add(a["keyword"])

    # 3) Perplexity citations (per market)
    for entry in ppx[-1:]:  # latest sample
        for market in (entry.get("by_market") or {}).values():
            for det in market.get("details", []):
                v_absent = not det.get("velluto_cited")
                for u in det.get("top_domains", []):
                    d = (u or "").lower().lstrip("www.")
                    if not d:
                        continue
                    t = _t(d)
                    t["ai_cited"] += 1
                    if v_absent:
                        t["ai_cited_velluto_absent"] += 1

    # Score
    for t in targets.values():
        s = 0
        s += 10 * len(t["keywords"])                 # category authority
        s += 40 if t["ai_cited"] else 0              # is an AI answer source
        s += 20 if t["ai_cited_velluto_absent"] else 0  # AI cites them, not us → get in
        if t["best_rank"] <= 3:
            s += 15
        elif t["best_rank"] <= 10:
            s += 8
        if t["type"] == "youtube":
            s += 10
        elif t["type"] == "reddit":
            s += 5
        t["score"] = s
        t["keywords"] = sorted(t["keywords"])[:6]

    ranked = sorted(targets.values(), key=lambda t: t["score"], reverse=True)
    seeding  = [t for t in ranked if t["type"] in ("editorial", "youtube", "reddit")][:20]
    stockist = [t for t in ranked if t["type"] == "retailer"][:8]
    return {"date": dt.date.today().isoformat(), "seeding": seeding, "stockist": stockist,
            "n_domains": len(targets)}


def _why(t: dict) -> str:
    bits = []
    if t["ai_cited_velluto_absent"]:
        bits.append("🤖 KI zitiert sie (uns nicht!)")
    elif t["ai_cited"]:
        bits.append("🤖 KI-Quelle")
    if t["best_rank"] <= 10:
        bits.append(f"rankt #{t['best_rank']}")
    if t["keywords"]:
        bits.append(f"für: {', '.join(t['keywords'][:3])}")
    return " · ".join(bits)


def digest(data: dict) -> str:
    L = [f"📮 Velluto Seeding-Ziele — {data['date']}  ({data['n_domains']} Domains analysiert)", ""]
    icon = {"editorial": "✍️", "youtube": "▶️", "reddit": "👥"}
    L.append("SEEDING (kostenlose StradaPro → Review/Backlink/Video):")
    for t in data["seeding"]:
        nm = f" ({t['name']})" if t["name"] else ""
        L.append(f"  {icon.get(t['type'],'•')} [{t['score']}] {t['domain']}{nm} — {_why(t)}")
    if data["stockist"]:
        L.append("")
        L.append("STOCKIST-Outreach (Händler, die ranken — Distribution):")
        for t in data["stockist"]:
            L.append(f"  🏪 {t['domain']} — rankt #{t['best_rank']} für {', '.join(t['keywords'][:2])}")
    L.append("")
    L.append("Priorität 1 = 🤖-Ziele: dort zitiert die KI, aber nicht Velluto — "
             "ein Review dort bringt dich ins AI-Answer-Set.")
    return "\n".join(L)


def main() -> None:
    force = "--force" in sys.argv
    if not gate_ok(force):
        print("   Seeding targets: sampled <7 days ago — nothing to do")
        return
    data = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({"last_run": data["date"]}, f)
    text = digest(data)
    print(text)
    if not data["seeding"] and not data["stockist"]:
        print("   (no SERP/AI data yet — run the research bundle first)")
        return
    try:
        import mailer
        mailer.send_email(f"📮 Velluto Seeding-Ziele — {data['date']}", text)
    except Exception as e:
        print(f"   ⚠️  email failed: {e}")


if __name__ == "__main__":
    main()
