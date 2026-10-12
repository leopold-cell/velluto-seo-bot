#!/usr/bin/env python3
"""
Perplexity GEO monitor — the second AI surface next to Google AI Overviews.

Perplexity answers cite their sources explicitly, which makes it the most
measurable LLM surface: we ask it the questions Velluto's buyers actually ask
(curated PAA clusters + top GSC queries) and check whether velluto-shop.com
appears among the citations.

Weekly + self-gating (runs as a daily run.sh step; only does work when the
last entry is >= 7 days old). Appends to data/perplexity_geo.json — the daily
report's GEO section shows the latest sample. READ-ONLY, fails soft.

ENV: PERPLEXITY_API_KEY (https://www.perplexity.ai/settings/api). Without it
the step skips silently. Cost: ~15 sonar queries/week ≈ a few cents.

Usage:
  python3 scripts/perplexity_monitor.py            # gated weekly
  python3 scripts/perplexity_monitor.py --force    # run now
"""
import datetime as dt
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from geo_questions import (  # noqa: E402
    GEO_MARKETS, ROOT, build_questions, domain_of, gate_ok,
    is_brand_question, load_json, repeats_for, tally,
)

load_dotenv(os.path.join(ROOT, ".env"), override=True)

REPEATS = repeats_for("perplexity")      # answers per question, see geo_questions

API_KEY  = os.getenv("PERPLEXITY_API_KEY", "")
HISTORY  = os.path.join(ROOT, "data", "perplexity_geo.json")
DOMAIN   = "velluto-shop.com"
MODEL    = "sonar"

# CORE_QUESTIONS / GEO_MARKETS / build_questions() / gate_ok() now live in
# scripts/geo_questions.py so this monitor and chatgpt_monitor.py ask the exact
# same questions and their rates stay comparable.


def _load(path: str, default):
    """Back-compat shim — geo_questions.load_json handles repo-relative paths too."""
    return load_json(path, default)


def ask(question: str) -> tuple[bool, bool, list[str]]:
    """(cited, mentioned, cited_domains) for ONE Perplexity answer.

    cited      velluto-shop.com is among the sources (or written out in the text)
    mentioned  the name appears in the text without a source link

    Brand questions (see geo_questions.is_brand_question) can never score a
    mention — the question already contains the name.
    """
    r = requests.post(
        "https://api.perplexity.ai/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}",
                 "Content-Type": "application/json"},
        json={"model": MODEL,
              "messages": [{"role": "user", "content": question}]},
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    urls: list[str] = []
    urls += [u for u in (data.get("citations") or []) if isinstance(u, str)]
    urls += [s.get("url", "") for s in (data.get("search_results") or [])
             if isinstance(s, dict)]
    text = ""
    try:
        text = data["choices"][0]["message"]["content"]
    except Exception:
        pass
    domains: list[str] = []
    for u in urls:
        d = domain_of(u)     # the old lstrip("www.") stripped CHARACTERS, not a prefix
        if d and d not in domains:
            domains.append(d)
    cited = any(DOMAIN in u for u in urls) or DOMAIN in text
    mentioned = (not cited) and (not is_brand_question(question)) \
        and "velluto" in text.lower()
    return cited, mentioned, domains


def main() -> None:
    force = "--force" in sys.argv
    if not API_KEY:
        print("   Perplexity: PERPLEXITY_API_KEY missing — skipping "
              "(create one at perplexity.ai/settings/api)")
        return
    hist = _load(HISTORY, [])
    if not gate_ok(hist, force, engine="perplexity"):
        print("   Perplexity: not due yet — nothing to do")
        return

    by_market, all_rows = {}, []
    for lang in GEO_MARKETS:
        questions = build_questions(lang)
        print(f"🔮 Perplexity GEO [{lang}] — {len(questions)} questions x {REPEATS} answers")
        rows = []
        for q in questions:
            cited_n = ment_n = ok = 0
            doms: list[str] = []
            for _ in range(REPEATS):
                try:
                    cited, mentioned, domains = ask(q)
                except Exception as e:
                    print(f"   ⚠️  '{q[:40]}': {e}")
                    continue
                ok += 1
                cited_n += int(cited)
                ment_n += int(mentioned)
                for d in domains:
                    if d not in doms:
                        doms.append(d)
                time.sleep(1)
            if not ok:
                continue
            kind = "brand" if is_brand_question(q) else "generic"
            rows.append({"question": q, "kind": kind, "runs": ok,
                         "cited": cited_n, "mentioned": ment_n,
                         # kept for geo_gaps.py, which reads a per-question boolean
                         "velluto_cited": bool(cited_n or ment_n) and kind == "generic"
                                          or bool(cited_n),
                         "top_domains": doms[:8]})
            flag = "🟢" if cited_n else ("🟡" if ment_n else "⚪")
            print(f"   {flag} [{lang}] {kind[:3]} {cited_n}+{ment_n}/{ok}  {q[:50]}")
        if rows:
            t = tally(rows)
            by_market[lang] = {"questions": len(rows), "details": rows, **t}
            all_rows += rows

    if not all_rows:
        print("   Perplexity: no successful queries — not recording")
        return
    t = tally(all_rows)
    # schema 2: top-level questions / velluto_cited / rate now describe GENERIC
    # answers only (the real visibility figure); brand answers are reported apart.
    entry = {"schema": 2, "date": dt.date.today().isoformat(), "repeats": REPEATS,
             "questions": t["generic_answers"], "velluto_cited": t["generic_visible"],
             "rate": t["generic_rate"], "by_market": by_market, **t}
    hist.append(entry)
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(hist[-52:], f, ensure_ascii=False, indent=1)
    lo, hi = t["generic_ci"]
    print(f"   ✓ GENERIC visibility {t['generic_visible']}/{t['generic_answers']} = "
          f"{t['generic_rate']}% (95%: {lo}–{hi}%) — cited {t['generic_cited']}, "
          f"mentioned {t['generic_mentioned']}")
    print(f"     brand questions: {t['brand_cited']}/{t['brand_answers']} cited (describability, "
          f"not recommendation)")


if __name__ == "__main__":
    main()
