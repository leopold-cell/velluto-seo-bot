#!/usr/bin/env python3
"""
Weekly Gemini visibility: do Gemini's Google-grounded answers cite or name Velluto?

WHY
The only evidence we ever had that Gemini recommends us is one customer email
(2026-10-05: asked Gemini for cheaper alternatives to the Oakley Sutro Lite, was
shown Velluto). Nothing in this repo measured Gemini at all.

HOW
Same questions and the same statistics as perplexity_monitor / chatgpt_monitor
(scripts/geo_questions.py), through the Gemini API with the google_search grounding
tool. Each question is asked GEO_REPEATS times because Gemini, like every engine,
answers the same prompt differently each time — the rate over many answers is the
measurement, a single answer is not (see geo_questions.py).

It also records `search_queries`: the sub-queries Gemini fired to build the answer
("query fan-out"). Those are far more stable than the answers and tell us which
searches our pages actually have to rank for. They feed the content plan.

CAVEATS, stated so nobody over-reads the number
- The API with grounding is a PROXY for the gemini.google.com app, not the same
  surface (personalisation, app-side retrieval and model version can differ).
- Not run yet when written: the response shape below follows the documented
  grounding schema (candidates[0].groundingMetadata.groundingChunks / .webSearchQueries)
  and was written defensively, but run `--dry-run` first and check the raw shape.
- Citation links in groundingChunks are Google redirect URLs; the cited site is in
  `web.title`, so the domain is read from there.

Needs GEMINI_API_KEY in .env (https://aistudio.google.com/apikey).

Usage:
  python3 scripts/gemini_monitor.py            # gated weekly
  python3 scripts/gemini_monitor.py --force
  python3 scripts/gemini_monitor.py --force --dry-run   # 1 question, show raw shape
  python3 scripts/gemini_monitor.py --list-models       # which model names this key can use
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
    GEO_MARKETS, REPEATS, ROOT, build_questions, domain_of, gate_ok,
    is_brand_question, load_json, tally,
)

load_dotenv(os.path.join(ROOT, ".env"), override=True)

API_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL   = os.getenv("GEMINI_MONITOR_MODEL", "gemini-2.5-flash")
HISTORY = os.path.join(ROOT, "data", "gemini_geo.json")
DOMAIN  = "velluto-shop.com"
BRAND   = "velluto"
URL     = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200"


def list_models() -> list[str]:
    """Model ids this key can call generateContent on, best monitor candidates first.

    Model names are retired on Google's schedule, not ours: 'gemini-2.5-flash' stopped
    resolving for this key (404). Asking the API what exists is more reliable than a
    name written into the code. Stable 'flash' models come first (cheap, grounded
    search); preview/experimental, lite, image, audio and live variants go last.
    """
    r = requests.get(MODELS_URL, headers={"x-goog-api-key": API_KEY}, timeout=30)
    r.raise_for_status()
    ids = []
    for m in r.json().get("models", []):
        if "generateContent" not in (m.get("supportedGenerationMethods") or []):
            continue
        name = (m.get("name") or "").removeprefix("models/")
        if name.startswith("gemini"):
            ids.append(name)

    def rank(n: str):
        bad = any(x in n for x in ("lite", "image", "tts", "audio", "live", "embedding",
                                   "thinking", "robotics", "computer"))
        pre = any(x in n for x in ("preview", "exp"))
        return (bad, pre, "flash" not in n, n)
    return sorted(ids, key=rank)


class FatalError(Exception):
    """Config-level failure: retrying the remaining questions cannot help."""


def _call(question: str) -> dict:
    r = requests.post(
        URL.format(model=MODEL),
        headers={"x-goog-api-key": API_KEY, "Content-Type": "application/json"},
        json={"contents": [{"parts": [{"text": question}]}],
              "tools": [{"google_search": {}}]},
        timeout=90,
    )
    if r.status_code in (400, 401, 403) and ("API key" in r.text or "API_KEY" in r.text
                                              or r.status_code in (401, 403)):
        raise FatalError("GEMINI_API_KEY is rejected. Create one at "
                         "aistudio.google.com/apikey and update .env.")
    if r.status_code == 404:
        try:
            cands = ", ".join(list_models()[:6])
        except Exception:
            cands = "(list failed — run: python3 scripts/gemini_monitor.py --list-models)"
        raise FatalError(f"Model '{MODEL}' not found for this key. Put one of these in "
                         f".env as GEMINI_MONITOR_MODEL=<name>: {cands}")
    if r.status_code == 429:
        raise FatalError("Gemini rate/quota limit (429) — check quota in AI Studio.")
    r.raise_for_status()
    return r.json()


def parse(data: dict, question: str) -> tuple[bool, bool, list[str], list[str]]:
    """(cited, mentioned, cited_domains, search_queries) from one raw response."""
    cand = (data.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", [])
                   if isinstance(p, dict))
    gm = cand.get("groundingMetadata") or {}
    domains: list[str] = []
    cited = DOMAIN in text
    for ch in gm.get("groundingChunks") or []:
        web = ch.get("web") or {}
        title = (web.get("title") or "").lower()
        uri = web.get("uri") or ""
        # The uri is a Google redirect; the title carries the site's domain.
        d = title if "." in title and " " not in title else domain_of(uri)
        if d and d not in domains:
            domains.append(d)
        if DOMAIN in title or DOMAIN in uri:
            cited = True
    mentioned = (not cited) and (not is_brand_question(question)) and BRAND in text.lower()
    return cited, mentioned, domains, [q for q in (gm.get("webSearchQueries") or [])
                                       if isinstance(q, str)]


def ask(question: str):
    return parse(_call(question), question)


def _dry_run() -> None:
    q = build_questions("en")[0]
    print(f"🔬 DRY-RUN · model={MODEL}\n   Q: {q}\n")
    data = _call(q)
    cand = (data.get("candidates") or [{}])[0]
    gm = cand.get("groundingMetadata") or {}
    print("   groundingMetadata keys :", sorted(gm.keys()))
    print("   webSearchQueries       :", gm.get("webSearchQueries"))
    print("   groundingChunks[:2]    :", json.dumps((gm.get("groundingChunks") or [])[:2],
                                                     ensure_ascii=False)[:300])
    cited, mentioned, domains, sq = parse(data, q)
    print(f"   parsed → cited={cited} mentioned={mentioned} domains={domains[:6]}")
    if not gm:
        print("\n   ⚠️  no groundingMetadata: the search tool did not run. Check the model "
              "supports google_search grounding before trusting any number.")


def main() -> None:
    force = "--force" in sys.argv
    if not API_KEY:
        print("   Gemini GEO: GEMINI_API_KEY missing — skipping "
              "(create one at aistudio.google.com/apikey)")
        return
    if "--list-models" in sys.argv:
        try:
            names = list_models()
        except Exception as e:
            print(f"   ✗ could not list models: {str(e)[:150]}")
            return
        print(f"{len(names)} models support generateContent for this key "
              f"(best monitor candidates first):")
        for n in names[:25]:
            print("  ", n)
        return
    if "--dry-run" in sys.argv:
        try:
            _dry_run()
        except FatalError as e:
            print(f"   ✗ {e}")
        return

    hist = load_json(HISTORY, [])
    if not gate_ok(hist, force):
        print("   Gemini GEO: sampled <7 days ago — nothing to do")
        return

    by_market, all_rows, fanout = {}, [], {}
    for lang in GEO_MARKETS:
        questions = build_questions(lang)
        print(f"♊ Gemini GEO [{lang}] — {len(questions)} questions x {REPEATS} answers")
        rows = []
        for q in questions:
            cited_n = ment_n = ok = 0
            doms: list[str] = []
            for _ in range(REPEATS):
                try:
                    cited, mentioned, domains, sq = ask(q)
                except FatalError as e:
                    print(f"   ✗ {e}\n   → nothing recorded; the baseline stays untouched.")
                    return
                except Exception as e:
                    print(f"   ⚠️  '{q[:40]}': {str(e)[:120]}")
                    continue
                ok += 1
                cited_n += int(cited)
                ment_n += int(mentioned)
                for d in domains:
                    if d not in doms:
                        doms.append(d)
                for s in sq:
                    fanout[s] = fanout.get(s, 0) + 1
                time.sleep(1)
            if not ok:
                continue
            kind = "brand" if is_brand_question(q) else "generic"
            rows.append({"question": q, "kind": kind, "runs": ok,
                         "cited": cited_n, "mentioned": ment_n,
                         "velluto_cited": bool(cited_n) or (kind == "generic" and bool(ment_n)),
                         "top_domains": doms[:8]})
            flag = "🟢" if cited_n else ("🟡" if ment_n else "⚪")
            print(f"   {flag} [{lang}] {kind[:3]} {cited_n}+{ment_n}/{ok}  {q[:50]}")
        if rows:
            by_market[lang] = {"questions": len(rows), "details": rows, **tally(rows)}
            all_rows += rows

    if not all_rows:
        print("   Gemini GEO: no successful queries — not recording")
        return
    t = tally(all_rows)
    top_fanout = sorted(fanout.items(), key=lambda kv: -kv[1])[:60]
    entry = {"schema": 2, "date": dt.date.today().isoformat(), "model": MODEL,
             "repeats": REPEATS, "questions": t["generic_answers"],
             "velluto_cited": t["generic_visible"], "rate": t["generic_rate"],
             "by_market": by_market, "search_queries": top_fanout, **t}
    hist.append(entry)
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(hist[-52:], f, ensure_ascii=False, indent=1)
    lo, hi = t["generic_ci"]
    print(f"   ✓ GENERIC visibility {t['generic_visible']}/{t['generic_answers']} = "
          f"{t['generic_rate']}% (95%: {lo}–{hi}%) — cited {t['generic_cited']}, "
          f"mentioned {t['generic_mentioned']}")
    print(f"     brand questions: {t['brand_cited']}/{t['brand_answers']} cited")
    print(f"     {len(fanout)} distinct fan-out queries recorded (data/gemini_geo.json)")


if __name__ == "__main__":
    main()
