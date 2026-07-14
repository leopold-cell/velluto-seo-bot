"""
EN Keyword Queue for Velluto SEO Bot
=====================================
Primary keyword source for the English magazine articles.
Keywords are pre-filtered to match Velluto's actual product range.

Volumes are estimates — update with real Ahrefs/GSC data when available.
To refresh the queue, add new entries to EN_KEYWORDS below and run the bot.
"""

import json
import os
import re

# ── Incompatibility filter ────────────────────────────────────────────────────
# Keywords matching any of these patterns cannot be served by Velluto's
# current product range and are excluded from the queue.
INCOMPATIBLE_PATTERNS = [
    r'photochromic',           # Velluto doesn't offer photochromic lenses
    r'photochrom',             # German/multilingual photochromic
    r'transition\s+lens',      # Transitions brand / photochromic
    r'self.?tinting',
    r'polariz',                # No polarized lenses
    r'polarised',
    r'prescription',           # No prescription option
    r'rx\s+cycling',
    r'\brx\b',                 # Rx abbreviation
    r'corrective\s+lens',
    r'optical\s+insert',       # Prescription insert clips
    r'over.{0,5}glass',        # "over glasses" / "over-glasses"
    r'clip.?on',               # Clip-on lens systems
    r'fit.?over',              # "fit over" glasses
    r'fits?\s+over',
    r'over\s+spectacles',
    r'mirror(ed)?\s+(lens|lenses|glass)',  # Mirrored lens claims
    r'progressive',            # Progressive / varifocal lenses
    r'varifocal',
    r'bifocal',
]


def is_compatible(keyword: str) -> bool:
    """Return True if the keyword can be served by Velluto's product range."""
    kw_lower = keyword.lower()
    return not any(re.search(p, kw_lower) for p in INCOMPATIBLE_PATTERNS)


# ── Keyword queue ─────────────────────────────────────────────────────────────
# Phase 1 = core commercial / high-intent (publish first)
# Phase 2 = comparison / buying-guide content
# Phase 3 = educational / informational (authority building)
#
# All volumes are US monthly search estimates.
# angle = optional content angle / unique hook for the article.

EN_KEYWORDS = [
    # ── Phase 1: Core commercial ──────────────────────────────────────────────
    # SunGod is being hyped as "The Oakley Replacement" (YouTube/Runner's World,
    # Jul 2026) and we have NO SunGod content yet — operator-prioritized.
    {
        "keyword": "SunGod alternative cycling glasses",
        "volume": 350, "phase": 1,
        "angle": "Mirror of the proven Oakley-alternatives winner: honest look at "
                 "what SunGod does well (custom colours, lifetime guarantee) and "
                 "where Velluto beats it — 25g weight, interchangeable lens system, "
                 "30-day risk-free trial, from 69 EUR vs SunGod's premium tiers.",
    },
    {
        "keyword": "SunGod vs Velluto cycling glasses",
        "volume": 150, "phase": 1,
        "angle": "Head-to-head comparison with a table: weight, lens tech, "
                 "customisation vs interchangeability, guarantee vs trial, price. "
                 "Fair on SunGod's strengths — credibility wins the comparison reader.",
    },
    {
        "keyword": "best cycling glasses",
        "volume": 2400, "phase": 1,
        "angle": "Top-pick roundup: what makes cycling glasses genuinely good vs "
                 "marketing fluff. Criteria: weight, UV rating, lens clarity, fit stability.",
    },
    {
        "keyword": "road cycling sunglasses",
        "volume": 1800, "phase": 1,
        "angle": "Road-specific needs: aerodynamics, wide lens coverage, clear vision "
                 "at speed. How road cycling glasses differ from casual sports sunglasses.",
    },
    {
        "keyword": "cycling glasses UV protection",
        "volume": 880, "phase": 1,
        "angle": "UV400 vs UV380 vs CE EN 1836 explained. Why UV matters more at "
                 "altitude and on long rides. How to verify UV rating on any pair.",
    },
    {
        "keyword": "lightweight cycling glasses",
        "volume": 720, "phase": 1,
        "angle": "Why grams matter: pressure behind ears, nose bridge pain on 4h rides. "
                 "What sub-30g actually feels like. Frame material trade-offs.",
    },
    {
        "keyword": "women's cycling glasses",
        "volume": 590, "phase": 1,
        "angle": "One-size vs fit — why face geometry matters more than gender labelling. "
                 "Adjustable nose pads and temple arms as the real differentiator.",
    },
    {
        "keyword": "gravel cycling glasses",
        "volume": 480, "phase": 1,
        "angle": "Gravel-specific demands: debris protection, temperature swings, "
                 "fog in forest sections. Why wrap-around matters more than on road.",
    },
    {
        "keyword": "cycling glasses interchangeable lenses",
        "volume": 390, "phase": 1,
        "angle": "The practical case for swappable lenses: one frame, multiple conditions. "
                 "When to use clear / yellow / smoke / tinted. How to swap without scratching.",
    },
    {
        "keyword": "anti fog cycling glasses",
        "volume": 320, "phase": 1,
        "angle": "Why glasses fog: temperature delta + humidity. Frame ventilation design "
                 "vs lens coating approaches. What actually works on long climbs.",
    },
    {
        "keyword": "cycling glasses for big head",
        "volume": 260, "phase": 1,
        "angle": "Head circumference vs face width — the actual measurements that matter. "
                 "Adjustable features to look for. Fit test without buying.",
    },
    {
        "keyword": "cycling sunglasses UV400",
        "volume": 210, "phase": 1,
        "angle": "UV400 decoded: what the standard means, how it protects against UVA+UVB, "
                 "why cheaper glasses often fail it.",
    },
    {
        "keyword": "best road bike sunglasses 2026",
        "volume": 180, "phase": 1,
        "angle": "2026 buyer's guide: what's changed, what to look for, how to avoid "
                 "overpaying for features that don't matter on the road.",
    },
    {
        "keyword": "cycling glasses small face",
        "volume": 170, "phase": 1,
        "angle": "Small face fit problems: glasses slipping, nose pads too wide, "
                 "temple arms too long. Adjustable vs fixed geometry.",
    },
    {
        "keyword": "Italian cycling glasses",
        "volume": 140, "phase": 1,
        "angle": "Italian design heritage in cycling eyewear: Briko, Rudy Project, "
                 "and the design philosophy of Italian-made frames.",
    },
    {
        "keyword": "MTB cycling glasses",
        "volume": 320, "phase": 1,
        "angle": "Mountain bike specific demands vs road: lower speeds, more debris, "
                 "wider FOV needed. StradaPro tested on singletrack and gravel.",
    },
    {
        "keyword": "cycling glasses for sportives",
        "volume": 120, "phase": 1,
        "angle": "Sportive-specific checklist: 100km+ comfort, all-day nose pad pressure, "
                 "lens swap between start and cols. What breaks at hour 6.",
    },

    # ── Phase 2: Comparison / review ─────────────────────────────────────────
    {
        "keyword": "cycling glasses review 2026",
        "volume": 480, "phase": 2,
        "angle": "Hands-on testing criteria: optical clarity (newspaper test), "
                 "frame flex, sweat resistance, fogging in 5°C descents.",
    },
    {
        "keyword": "cycling sunglasses buying guide",
        "volume": 320, "phase": 2,
        "angle": "Decision framework: lens tint vs conditions, fit priority over brand, "
                 "budget tiers (€60 / €120 / €180+), what to skip.",
    },
    {
        "keyword": "road bike glasses comparison",
        "volume": 260, "phase": 2,
        "angle": "Side-by-side spec analysis: weight, lens options, adjustability, "
                 "price-per-feature at €100–€200 tier.",
    },
    {
        "keyword": "best glasses for cycling in sun",
        "volume": 210, "phase": 2,
        "angle": "Bright-light lens guide: smoke vs brown vs orange for different "
                 "sun conditions. When to use which tint.",
    },
    {
        "keyword": "cycling glasses vs sunglasses",
        "volume": 190, "phase": 2,
        "angle": "Why standard sunglasses fail on the bike: peripheral gaps, "
                 "no ventilation, slipping at speed. The 5 key differences.",
    },
    {
        "keyword": "cycling glasses lens colors guide",
        "volume": 150, "phase": 2,
        "angle": "Lens tint decision tree: clear for night/rain, yellow for low light, "
                 "smoke for sun, brown/amber for contrast. When each wins.",
    },
    {
        "keyword": "cycling glasses under 200 euros",
        "volume": 130, "phase": 2,
        "angle": "Premium vs mid-range: what you actually get for €200 vs €120 vs €80. "
                 "Where the real value break-point is.",
    },

    # ── Phase 3: Educational / authority ─────────────────────────────────────
    {
        "keyword": "how to choose cycling glasses",
        "volume": 640, "phase": 3,
        "angle": "Step-by-step decision guide: face shape → fit → lens → conditions → budget. "
                 "The one thing most buyers get wrong.",
    },
    {
        "keyword": "UV protection for cyclists eyes",
        "volume": 260, "phase": 3,
        "angle": "Medical case for eye protection on the bike: UVA/UVB cumulative damage, "
                 "altitude amplification, why cyclists are high-risk.",
    },
    {
        "keyword": "cycling glasses fit guide",
        "volume": 210, "phase": 3,
        "angle": "How to measure your face for cycling glasses. The 3 fit points that "
                 "matter: nose bridge, temple grip, lens coverage.",
    },
    {
        "keyword": "why wear cycling glasses",
        "volume": 180, "phase": 3,
        "angle": "The non-obvious reasons: insects at 35 km/h, UV cumulative damage, "
                 "wind tear reflex affecting vision, gravel spray.",
    },
    {
        "keyword": "cycling glasses for long distance rides",
        "volume": 150, "phase": 3,
        "angle": "Comfort at hour 4+: pressure distribution, ventilation, lens clarity "
                 "fatigue. What fails on 200km rides that's fine on 60km.",
    },
    {
        "keyword": "cycling glasses care and cleaning",
        "volume": 130, "phase": 3,
        "angle": "How to clean cycling lenses without micro-scratching. Storage, "
                 "anti-fog maintenance, when to replace lenses.",
    },
    {
        "keyword": "cycling eye protection importance",
        "volume": 110, "phase": 3,
        "angle": "Eye injuries in cycling: statistics, common causes, how proper "
                 "eyewear prevents the most frequent incidents.",
    },
]


# ── Queue management ──────────────────────────────────────────────────────────

_QUEUE_DIR = os.path.dirname(os.path.abspath(__file__))
EN_USED_LOG = os.path.join(_QUEUE_DIR, "en_keywords_used.json")


def _load_used() -> set:
    if os.path.exists(EN_USED_LOG):
        return set(json.load(open(EN_USED_LOG, encoding="utf-8")))
    return set()


def _save_used(used: set) -> None:
    json.dump(sorted(used), open(EN_USED_LOG, "w", encoding="utf-8"), indent=2)


def get_next_en_keyword() -> dict | None:
    """Return the next unused, compatible keyword (lowest phase first, then order in list)."""
    used = _load_used()
    for kw in sorted(EN_KEYWORDS, key=lambda k: k["phase"]):
        if kw["keyword"] not in used and is_compatible(kw["keyword"]):
            return kw
    return None


def mark_en_keyword_used(keyword: str) -> None:
    """Mark a keyword as used so it won't be returned again."""
    used = _load_used()
    used.add(keyword)
    _save_used(used)


def get_en_queue_status() -> dict:
    """Return a summary of queue progress."""
    used = _load_used()
    by_phase: dict[str, dict] = {}
    for kw in EN_KEYWORDS:
        p = str(kw["phase"])
        entry = by_phase.setdefault(p, {"total": 0, "done": 0})
        entry["total"] += 1
        if kw["keyword"] in used:
            entry["done"] += 1
    return {
        "total": len(EN_KEYWORDS),
        "used":  len(used),
        "by_phase": by_phase,
    }


if __name__ == "__main__":
    # Quick CLI check
    status = get_en_queue_status()
    print(f"Queue: {status['total'] - status['used']} remaining / {status['total']} total")
    nxt = get_next_en_keyword()
    if nxt:
        print(f"Next: [{nxt['phase']}] {nxt['keyword']}")
        print(f"  Vol: {nxt['volume']} | Angle: {nxt.get('angle', '')[:80]}")
    else:
        print("Queue exhausted.")
