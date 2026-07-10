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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"), override=True)

API_KEY  = os.getenv("PERPLEXITY_API_KEY", "")
HISTORY  = os.path.join(ROOT, "data", "perplexity_geo.json")
DOMAIN   = "velluto-shop.com"
MODEL    = "sonar"
MAX_QUESTIONS = 15

# Core buyer questions — always asked, independent of PAA/GSC availability.
CORE_QUESTIONS = [
    "What are the best cycling glasses in 2026?",
    "What are the best Oakley alternatives for road cycling?",
    "What are the best lightweight cycling sunglasses?",
    "Are Velluto cycling glasses any good?",
    "Which cycling glasses have interchangeable lenses?",
]


def _load(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def build_questions() -> list[str]:
    """CORE + curated PAA seed + top GSC queries (as questions), deduped."""
    out = list(CORE_QUESTIONS)
    seed = _load(os.path.join(ROOT, "data", "paa_seed.json"), {})
    for cluster, qs in seed.items():
        if not cluster.startswith("_"):
            out += [q for q in qs if isinstance(q, str)]
    gsc = _load(os.path.join(ROOT, "gsc_data.json"), {})
    for row in (gsc.get("top_queries") or [])[:5]:
        kw = (row.get("keys") or [""])[0]
        if kw and kw.lower() != "velluto":
            out.append(f"What are the {kw}?" if not kw.endswith("?") else kw)
    return list(dict.fromkeys(out))[:MAX_QUESTIONS]


def ask(question: str) -> tuple[bool, list[str]]:
    """(velluto_cited, cited_domains) for one Perplexity query."""
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
    # answer text can mention the brand even without a formal citation
    text = ""
    try:
        text = data["choices"][0]["message"]["content"]
    except Exception:
        pass
    domains = []
    for u in urls:
        d = u.split("//")[-1].split("/")[0].lstrip("www.")
        if d and d not in domains:
            domains.append(d)
    cited = any(DOMAIN in u for u in urls) or DOMAIN in text or "velluto" in text.lower()
    return cited, domains


def gate_ok(hist: list[dict], force: bool) -> bool:
    if force or not hist:
        return True
    try:
        last = dt.date.fromisoformat(hist[-1]["date"])
        return (dt.date.today() - last).days >= 7
    except Exception:
        return True


def main() -> None:
    force = "--force" in sys.argv
    if not API_KEY:
        print("   Perplexity: PERPLEXITY_API_KEY missing — skipping "
              "(create one at perplexity.ai/settings/api)")
        return
    hist = _load(HISTORY, [])
    if not gate_ok(hist, force):
        print("   Perplexity: sampled <7 days ago — nothing to do")
        return

    questions = build_questions()
    print(f"🔮 Perplexity GEO sample — {len(questions)} questions")
    details, cited_n = [], 0
    for q in questions:
        try:
            cited, domains = ask(q)
        except Exception as e:
            print(f"   ⚠️  '{q[:40]}': {e}")
            continue
        cited_n += int(cited)
        details.append({"question": q, "velluto_cited": cited,
                        "top_domains": domains[:5]})
        print(f"   {'🟢' if cited else '⚪'} {q[:60]}")
        time.sleep(1)

    if not details:
        print("   Perplexity: no successful queries — not recording")
        return
    entry = {"date": dt.date.today().isoformat(),
             "questions": len(details), "velluto_cited": cited_n,
             "rate": round(cited_n / len(details) * 100, 1),
             "details": details}
    hist.append(entry)
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(hist[-52:], f, ensure_ascii=False, indent=1)
    print(f"   ✓ Velluto cited in {cited_n}/{len(details)} answers "
          f"({entry['rate']}%) — history: {HISTORY}")


if __name__ == "__main__":
    main()
