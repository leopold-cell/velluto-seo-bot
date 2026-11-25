#!/usr/bin/env python3
"""
Which sites do the AI engines cite for our buyer questions, and where are we missing?

Ramp's case study (Nov 2026, second-hand): AI mentions went to pages the engines already
cited; getting named on THOSE pages beat publishing more of our own. The monitors already
record, per generic question, the domains each engine cited (top_domains). This pools the
last WINDOW runs of every engine, ranks the domains, and lists the ones that are cited
often but never carry us: the outreach targets (review, retailer listing, mention).

No API calls: reads data/*_geo.json only. Writes data/ai_source_map.json and prints the top.
Gated weekly by the date of the last map; --force to rerun.

Usage:
  python3 scripts/ai_source_map.py
"""
import datetime as dt
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "ai_source_map.json")
ENGINES = {"gemini": "data/gemini_geo.json", "perplexity": "data/perplexity_geo.json",
           "chatgpt": "data/chatgpt_geo.json"}
WINDOW = 4          # most recent runs per engine
OWN = "velluto-shop.com"
# Not outreach targets: aggregators and platforms we cannot "get listed" on.
SKIP = {"youtube.com", "reddit.com", "wikipedia.org", "amazon.com", "facebook.com"}


def _load(path):
    try:
        return json.load(open(os.path.join(ROOT, path), encoding="utf-8"))
    except Exception:
        return []


def main() -> None:
    try:
        last = json.load(open(OUT, encoding="utf-8")).get("date")
        if last and (dt.date.today() - dt.date.fromisoformat(last)).days < 7 and "--force" not in sys.argv:
            print("   AI-Quellenkarte: noch aktuell, nichts zu tun")
            return
    except Exception:
        pass
    total, per_engine, answers = Counter(), {}, {}
    for eng, path in ENGINES.items():
        runs = [e for e in _load(path) if isinstance(e, dict)][-WINDOW:]
        c = Counter()
        n = 0
        for e in runs:
            for m in (e.get("by_market") or {}).values():
                for row in m.get("details", []):
                    if row.get("kind") != "generic":
                        continue
                    n += int(row.get("runs", 1))
                    for d in row.get("top_domains", []):
                        c[d] += 1
        per_engine[eng] = c
        answers[eng] = n
        total.update(c)
    ranked = []
    for d, n in total.most_common(60):
        ranked.append({"domain": d, "questions_cited": n,
                       **{eng: per_engine[eng].get(d, 0) for eng in ENGINES}})
    targets = [r for r in ranked if r["domain"] != OWN and r["domain"] not in SKIP][:15]
    entry = {"date": dt.date.today().isoformat(), "window_runs": WINDOW,
             "generic_answers": answers, "own_citations": total.get(OWN, 0),
             "outreach_targets": targets, "ranking": ranked}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(entry, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"   AI-Quellenkarte: {sum(answers.values())} Antworten, "
          f"wir selbst {total.get(OWN, 0)}x zitiert. Meistzitierte fremde Quellen:")
    for r in targets[:10]:
        print(f"     {r['domain']:<28} {r['questions_cited']:>3}  "
              f"(gemini {r['gemini']}, perplexity {r['perplexity']}, chatgpt {r['chatgpt']})")


if __name__ == "__main__":
    main()
