"""
PAA extractor — reads serp_snapshots.json, extracts People-Also-Ask questions,
classifies intent + scores buyer_intent 0-100 per question.

Intent classes (matched against the question text):
  - commercial_investigation : "which / what / are X worth"
  - buying_criteria          : "what to look for / what is important"
  - price_objection          : "worth it / expensive / cheap / vs"
  - problem_solution         : "fog / wind / watery / pain / fit"
  - comparison               : "vs / oder / or / better"
  - educational              : default

Output: data/processed/paa_snapshots.json
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from typing import Any

import config_loader
from research import serp_fetcher

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "processed", "paa_snapshots.json",
)


INTENT_PATTERNS: list[tuple[str, str, int]] = [
    # (regex, intent_label, buyer_intent_score)
    (r"\b(worth it|lohnt sich|de moeite waard|vale la pena|merece la pena)\b",
                                                      "price_objection",          95),
    (r"\b(vs\.?|oder|or|or which|better than)\b",     "comparison",               90),
    (r"\bbest\b|\bbeste\b|\bbeter\b|\bmeilleur\b|\bmigliori\b|\bmejor\b",
                                                      "commercial_investigation", 90),
    (r"\b(what (should|to) (look|consider))\b|\b(was ist wichtig)\b|\b(worauf achten)\b",
                                                      "buying_criteria",          90),
    (r"\b(fog|fogging|beschlägt|beslaat|appann|emba(ç|c)a)\b",
                                                      "problem_solution",         80),
    (r"\b(wind|watery|tränende|tranende|lacrim|ojos|llorosos)\b",
                                                      "problem_solution",         80),
    (r"\b(uv|uv400|uv-?protection|uv-?schutz)\b",     "buying_criteria",          75),
    (r"\b(photochromic|selbsttönend|meekleurend|fotocromat)\b",
                                                      "comparison",               80),
    (r"\b(price|expensive|cheap|preis|prijs|prezzo|precio|prix)\b",
                                                      "price_objection",          70),
    (r"\b(how (should|much|big)|hoe|wie|come|comment|cómo)\b",
                                                      "educational",              50),
]


def classify(question: str) -> tuple[str, int]:
    """Return (intent_label, buyer_intent_score 0-100) for a question."""
    q = question.lower()
    for pattern, label, score in INTENT_PATTERNS:
        if re.search(pattern, q, re.IGNORECASE):
            return label, score
    return "educational", 40


def _flatten_paa(paa_items: list[dict]) -> list[str]:
    """DataForSEO PAA structure: items[type=people_also_ask].items[] each with title."""
    questions: list[str] = []
    for grp in paa_items:
        for sub in (grp.get("items") or []):
            t = sub.get("title") or sub.get("question")
            if t:
                questions.append(t.strip())
    # Dedupe preserving order
    seen = set()
    out = []
    for q in questions:
        if q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out


def run() -> dict:
    """
    Read latest SERP snapshot, build per-(market,keyword) PAA classification.
    Output: list of {market, keyword, questions: [{question, intent, score}]}
    """
    serp = serp_fetcher.load_latest()
    if not serp or not serp.get("snapshots"):
        result = {"date": _dt.date.today().isoformat(), "extracted": [],
                  "total_questions": 0, "high_intent_questions": 0}
        _save(result)
        print("   PAA: no SERP snapshot to parse")
        return result

    extracted = []
    total_q   = 0
    high_q    = 0

    for snap in serp["snapshots"]:
        questions = _flatten_paa(snap.get("people_also_ask") or [])
        classified = []
        for q in questions:
            label, score = classify(q)
            classified.append({
                "question":           q,
                "intent":             label,
                "buyer_intent_score": score,
                "recommended_section": "H2" if score >= 70 else "H3",
            })
            total_q += 1
            if score >= 75:
                high_q += 1
        if classified:
            extracted.append({
                "market":     snap["market"],
                "keyword":    snap["keyword"],
                "questions":  classified,
            })

    result = {
        "date":                  _dt.date.today().isoformat(),
        "extracted":             extracted,
        "total_questions":       total_q,
        "high_intent_questions": high_q,
    }
    _save(result)
    print(f"   ✓ PAA: {total_q} questions ({high_q} high-intent) across "
          f"{len(extracted)} (market,keyword) snapshots")
    return result


def _save(payload: dict) -> None:
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    result = run()
    print(json.dumps({k: v for k, v in result.items() if k != "extracted"}, indent=2))
