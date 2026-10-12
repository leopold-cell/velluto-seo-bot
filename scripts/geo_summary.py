#!/usr/bin/env python3
"""
One honest table: generic-question visibility per AI engine, pooled over a window,
with a 95% interval, and a verdict on whether it moved.

WHY NOT WEEK-ON-WEEK
Engines answer the same prompt differently every time (see geo_questions.py for the
numbers). A weekly rate built from a few dozen answers swings by several points on
chance alone, so "10% -> 15% this week" means nothing. This pools the last WINDOW
weeks, pools the WINDOW weeks before, and calls the change real only when the two
95% intervals do not overlap. Otherwise it says "no detectable change" — which, at
a 1% base rate, is the honest answer for a long time.

Old (schema-1) history is restated on the same terms: its per-question flags are
re-split into generic vs brand questions, so the Perplexity series from July on
becomes comparable with everything recorded from now on.

Usage:
  python3 scripts/geo_summary.py             # print + write data/geo_summary.json
  python3 scripts/geo_summary.py --window 4
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from geo_questions import ROOT, load_json, tally, wilson  # noqa: E402

ENGINES = {"Perplexity": "data/perplexity_geo.json",
           "ChatGPT":    "data/chatgpt_geo.json",
           "Gemini":     "data/gemini_geo.json"}
OUT = os.path.join(ROOT, "data", "geo_summary.json")


def _int_arg(flag: str, default: int) -> int:
    if flag in sys.argv:
        try:
            return max(1, int(sys.argv[sys.argv.index(flag) + 1]))
        except (ValueError, IndexError):
            pass
    return default


def entry_rows(entry: dict) -> list[dict]:
    """Per-question rows from one history entry, schema 1 or 2."""
    rows = []
    for m in (entry.get("by_market") or {}).values():
        for d in m.get("details", []):
            if "runs" in d:                                   # schema 2
                rows.append(d)
            else:                                             # schema 1: one answer
                hit = bool(d.get("velluto_cited"))
                rows.append({"question": d.get("question", ""), "runs": 1,
                             "cited": int(hit), "mentioned": 0})
    return rows


def pool(entries: list[dict]) -> dict:
    rows = [r for e in entries for r in entry_rows(e)]
    return tally(rows) if rows else tally([])


def verdict(now: dict, before: dict) -> str:
    if not now["generic_answers"]:
        return "keine Daten"
    if not before["generic_answers"]:
        return "Baseline (kein Vergleichszeitraum)"
    lo_n, hi_n = now["generic_ci"]
    lo_b, hi_b = before["generic_ci"]
    if lo_n > hi_b:
        return "▲ gestiegen (Intervalle überlappen nicht)"
    if hi_n < lo_b:
        return "▼ gefallen (Intervalle überlappen nicht)"
    return "keine nachweisbare Veränderung"


def main() -> None:
    window = _int_arg("--window", 4)
    result = {}
    print(f"GEO-Sichtbarkeit auf ALLGEMEINE Fragen (Markenfragen ausgeklammert), "
          f"Fenster = {window} Wochen\n")
    for name, path in ENGINES.items():
        hist = load_json(path, [])
        if not hist:
            print(f"  {name:11} noch keine Messung")
            continue
        now = pool(hist[-window:])
        before = pool(hist[-2 * window:-window])
        lo, hi = now["generic_ci"]
        print(f"  {name:11} {now['generic_visible']:3}/{now['generic_answers']:<4} = "
              f"{now['generic_rate']:5.2f}%   95%: {lo:.1f}–{hi:.1f}%   "
              f"{verdict(now, before)}")
        result[name] = {"now": now, "before": before, "verdict": verdict(now, before),
                        "last": hist[-1].get("date")}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
