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
    out = list(dict.fromkeys(out))[:MAX_QUESTIONS]
    # Brand questions ("Are Velluto glasses any good?") are not asked by default: the
    # answer always names the brand, so they measure nothing about visibility, and
    # every one costs a paid call per engine per run. GEO_INCLUDE_BRAND=1 brings them
    # back, e.g. for an occasional check that engines can describe us correctly.
    if os.getenv("GEO_INCLUDE_BRAND", "0") != "1":
        out = [q for q in out if "velluto" not in q.lower()]
    return out


# ── Measurement statistics ────────────────────────────────────────────────────
# Why this exists. Two flaws made the first 14 weeks of GEO data close to useless:
#
# 1. A brand question names the brand. "Are Velluto cycling glasses any good?" gets
#    an answer containing "Velluto" every time, whatever the engine knows — so
#    perplexity_monitor counted it as a hit, 52 of 52. The headline 10-15% was four
#    questions that cannot miss. Brand questions say whether an engine can describe
#    us; they say nothing about whether it recommends us. Only GENERIC questions
#    measure visibility, and there the rate was 6 of 468 = 1.3%.
#
# 2. One sample per question per week. Engines answer the same prompt differently
#    every time: SparkToro/Gumshoe (Nov-Dec 2025, 2,961 prompts, 60-100 runs each,
#    not peer-reviewed) saw the same brand list under 1% of the time on ChatGPT and
#    Google AI. A single answer is a coin flip, so week-on-week movements of a few
#    points are noise. The defensible quantity is a RATE over many answers, with an
#    interval, compared between periods.
# Answers collected per question, per engine. Cost is per answer, and what the
# interval depends on is the TOTAL number of generic answers pooled over the window
# (see geo_summary.py), not on re-asking one question many times. So the default is
# deliberately lean, and ChatGPT — by far the most expensive per call because every
# answer pays a web-search fee plus the search content as tokens — gets one answer
# per question. Override per engine with GEO_REPEATS_<ENGINE>, or all with GEO_REPEATS.
_REPEAT_DEFAULTS = {"perplexity": 2, "gemini": 2, "chatgpt": 1}


def repeats_for(engine: str) -> int:
    for key in (f"GEO_REPEATS_{engine.upper()}", "GEO_REPEATS"):
        v = os.getenv(key, "").strip()
        if v.isdigit() and int(v) > 0:
            return int(v)
    return _REPEAT_DEFAULTS.get(engine.lower(), 2)

import math


def is_brand_question(question: str) -> bool:
    """True when the question itself contains the brand — see flaw 1 above."""
    return "velluto" in (question or "").lower()


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for k hits in n answers, in percent. Wilson rather than
    the textbook normal interval: at a true rate near 1% the normal one dips below
    zero and is wrong exactly where we operate."""
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half) * 100, min(1.0, centre + half) * 100)


def tally(rows: list[dict]) -> dict:
    """Split per-question rows into generic vs brand and pool them.

    A row is {question, runs, cited, mentioned}: of `runs` answers, `cited` carried
    a velluto-shop.com source and `mentioned` named Velluto without one. For
    GENERIC questions visibility = cited + mentioned. For BRAND questions only
    `cited` is meaningful (a mention is an echo of the question).
    """
    g_n = g_cit = g_men = b_n = b_cit = 0
    for r in rows:
        n = int(r.get("runs", 1))
        if is_brand_question(r.get("question", "")):
            b_n += n
            b_cit += int(r.get("cited", 0))
        else:
            g_n += n
            g_cit += int(r.get("cited", 0))
            g_men += int(r.get("mentioned", 0))
    vis = g_cit + g_men
    lo, hi = wilson(vis, g_n)
    return {"generic_answers": g_n, "generic_cited": g_cit, "generic_mentioned": g_men,
            "generic_visible": vis,
            "generic_rate": round(vis / g_n * 100, 2) if g_n else 0.0,
            "generic_ci": [round(lo, 2), round(hi, 2)],
            "brand_answers": b_n, "brand_cited": b_cit}


_GATE_DEFAULTS = {"chatgpt": 14}      # days; every other engine runs weekly


def gate_days_for(engine: str | None) -> int:
    """Days between runs. ChatGPT is the expensive engine (search fee plus search
    content as tokens on every answer), so it samples every 14 days; Perplexity and
    Gemini are cheap or free and stay weekly, which also makes them the early warning
    for a dead key or a retired endpoint. Override per engine with
    GEO_GATE_DAYS_<ENGINE>, or all at once with GEO_GATE_DAYS."""
    if engine:
        v = os.getenv(f"GEO_GATE_DAYS_{engine.upper()}", "").strip()
        if v.isdigit() and int(v) > 0:
            return int(v)
    v = os.getenv("GEO_GATE_DAYS", "").strip()
    if v.isdigit() and int(v) > 0:
        return int(v)
    return _GATE_DEFAULTS.get((engine or "").lower(), 7)


def gate_ok(hist: list, force: bool, days: int | None = None,
            engine: str | None = None) -> bool:
    """True when the last history entry is >= `days` old (or there is none)."""
    if days is None:
        days = gate_days_for(engine)
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
