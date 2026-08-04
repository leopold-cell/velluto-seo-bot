#!/usr/bin/env python3
"""
Shared question bank + gating for the AI-visibility monitors.

Both scripts/perplexity_monitor.py and scripts/chatgpt_monitor.py ask the SAME
buyer questions on their respective surfaces, so the two citation rates are
directly comparable. Keeping the bank here means a question added once shows up
in both measurements instead of drifting apart.

Not a runnable script — import only.
"""
import datetime as dt
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAX_QUESTIONS = 10   # per market

# Native core buyer questions per market — GEO is measured in the language the
# buyer actually asks (a DACH cyclist asks in German). Markets mirror the shop's
# revenue markets. English ("en") stays the baseline.
CORE_QUESTIONS = {
    "en": [
        "What are the best cycling glasses in 2026?",
        "What are the best Oakley alternatives for road cycling?",
        "What are the best lightweight cycling sunglasses?",
        "Are Velluto cycling glasses any good?",
        "Which cycling glasses have interchangeable lenses?",
    ],
    "de": [
        "Was sind die besten Fahrradbrillen 2026?",
        "Was ist die beste Alternative zu Oakley Fahrradbrillen?",
        "Welche Rennradbrille hat Wechselgläser?",
        "Sind Velluto Fahrradbrillen gut?",
        "Was ist die beste leichte Rennradbrille?",
    ],
    "nl": [
        "Wat is de beste wielrenbril in 2026?",
        "Wat is het beste alternatief voor een Oakley wielrenbril?",
        "Welke fietsbril heeft verwisselbare glazen?",
        "Zijn Velluto fietsbrillen goed?",
        "Wat is de beste lichte wielrenbril?",
    ],
    "fr": [
        "Quelles sont les meilleures lunettes de vélo en 2026 ?",
        "Quelle est la meilleure alternative aux lunettes Oakley pour le vélo ?",
        "Quelles lunettes de cyclisme ont des verres interchangeables ?",
        "Les lunettes de vélo Velluto sont-elles bonnes ?",
        "Quelles sont les meilleures lunettes de vélo légères ?",
    ],
}

# Markets to sample each week (native GEO visibility). Keep small for cost.
GEO_MARKETS = ["en", "de", "nl", "fr"]


def load_json(path: str, default):
    """Read a repo-relative or absolute JSON file. Never raises."""
    try:
        full = path if os.path.isabs(path) else os.path.join(ROOT, path)
        with open(full, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def build_questions(lang: str = "en") -> list[str]:
    """Native CORE + curated PAA seed for that market, deduped, capped.
    English also folds in the top GSC queries."""
    out = list(CORE_QUESTIONS.get(lang, CORE_QUESTIONS["en"]))
    seed = load_json(os.path.join("data", "paa_seed.json"), {})
    market = seed.get(lang) if isinstance(seed.get(lang), dict) else None
    # legacy flat structure counts as English
    if market is None and lang == "en":
        market = {k: v for k, v in seed.items()
                  if not k.startswith("_") and isinstance(v, list)}
    for qs in (market or {}).values():
        out += [q for q in qs if isinstance(q, str)]
    if lang == "en":
        gsc = load_json("gsc_data.json", {})
        for row in (gsc.get("top_queries") or [])[:5]:
            kw = (row.get("keys") or [""])[0]
            if kw and kw.lower() != "velluto":
                out.append(f"What are the {kw}?" if not kw.endswith("?") else kw)
    return list(dict.fromkeys(out))[:MAX_QUESTIONS]


def gate_ok(hist: list, force: bool, days: int = 7) -> bool:
    """True when the last history entry is >= `days` old (or there is none)."""
    if force or not hist:
        return True
    try:
        last = dt.date.fromisoformat(hist[-1]["date"])
        return (dt.date.today() - last).days >= days
    except Exception:
        return True


def domain_of(url: str) -> str:
    """Bare registrable-ish host for a URL ('' when unparseable)."""
    if not isinstance(url, str) or "//" not in url and "." not in url:
        return ""
    host = url.split("//")[-1].split("/")[0].split("?")[0].lower()
    return host[4:] if host.startswith("www.") else host
