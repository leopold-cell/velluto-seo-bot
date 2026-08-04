#!/usr/bin/env python3
"""
ChatGPT visibility monitor — the AI surface that was never measured.

geo_monitor.py measures Google AI Overviews, perplexity_monitor.py measures
Perplexity. This closes the gap: it asks the SAME buyer questions (shared bank
in scripts/geo_questions.py) via the OpenAI Responses API with the web_search
tool, and records whether velluto-shop.com shows up as a cited source.

WHAT THIS IS AND IS NOT
  The API with web_search is a PROXY for chatgpt.com, not the same surface.
  Model, retrieval and ranking differ from what a human sees in the ChatGPT app.
  Read the TREND (are we gaining ground?), not the absolute number.

TWO METRICS, DELIBERATELY SEPARATED
  cited     — velluto-shop.com appears in the answer's url_citation annotations.
              This is the headline rate.
  mentioned — the brand name appears in the answer text without a source link.
              Worth knowing (brand awareness) but NOT a citation.
  perplexity_monitor.py conflates the two, which overstates its rate; this one
  does not. Compare the `cited` rates when comparing surfaces.

Weekly + self-gating (runs as a daily run.sh step; only works when the last
entry is >= 7 days old). Appends to data/chatgpt_geo.json. READ-ONLY, fails soft.

ENV: OPENAI_API_KEY (already configured — image_generator.py uses it).
     CHATGPT_MONITOR_MODEL to override the model (default below).
Cost: ~40 web-search calls/week. Billed per tool call, so expect roughly
      $0.40-1.00/week, not "a few cents". Printed per run.

Usage:
  python3 scripts/chatgpt_monitor.py            # gated weekly
  python3 scripts/chatgpt_monitor.py --force    # run now
  python3 scripts/chatgpt_monitor.py --force --dry-run   # 1 question, show raw shape
"""
import datetime as dt
import json
import os
import sys
import time

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from geo_questions import (  # noqa: E402
    GEO_MARKETS, ROOT, build_questions, domain_of, gate_ok, load_json,
)

load_dotenv(os.path.join(ROOT, ".env"), override=True)

API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL   = os.getenv("CHATGPT_MONITOR_MODEL", "gpt-5")
HISTORY = os.path.join(ROOT, "data", "chatgpt_geo.json")
DOMAIN  = "velluto-shop.com"
BRAND   = "velluto"


def _iter_annotations(payload) -> list[dict]:
    """Walk the response payload and collect every annotation dict.

    Written defensively on purpose: the Responses API nests citations as
    output[].content[].annotations[] with type 'url_citation', but the exact
    nesting has moved between SDK versions. A recursive walk keeps this working
    instead of silently reporting zero citations after an SDK bump.
    """
    found: list[dict] = []

    def walk(node):
        if isinstance(node, dict):
            for key, val in node.items():
                if key == "annotations" and isinstance(val, list):
                    found.extend(a for a in val if isinstance(a, dict))
                else:
                    walk(val)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found


def ask(client, question: str) -> tuple[bool, bool, list[str]]:
    """(cited, mentioned, cited_domains) for one web-grounded ChatGPT answer."""
    resp = client.responses.create(
        model=MODEL,
        tools=[{"type": "web_search"}],
        input=question,
    )

    try:
        payload = resp.model_dump()
    except Exception:
        payload = json.loads(resp.model_dump_json())

    urls: list[str] = []
    for ann in _iter_annotations(payload):
        if ann.get("type") in (None, "url_citation") and ann.get("url"):
            urls.append(ann["url"])

    domains: list[str] = []
    for u in urls:
        d = domain_of(u)
        if d and d not in domains:
            domains.append(d)

    text = ""
    try:
        text = resp.output_text or ""
    except Exception:
        pass

    cited = any(DOMAIN in u for u in urls) or DOMAIN in text
    mentioned = (not cited) and BRAND in text.lower()
    return cited, mentioned, domains


def _fatal_reason(exc: Exception) -> str:
    """Actionable one-liner for errors where retrying the other 39 questions is
    pointless, '' when the error is per-question and the loop should continue.

    A dead key used to surface as 40 stack-trace-ish warnings followed by
    'no successful queries' — correct outcome, cause buried in the noise.
    """
    msg = str(exc)
    name = type(exc).__name__
    if name == "AuthenticationError" or "401" in msg or "invalid_api_key" in msg:
        return ("OPENAI_API_KEY is rejected (401). Rotate it at "
                "platform.openai.com/api-keys and update .env.")
    if name == "RateLimitError" or "429" in msg or "insufficient_quota" in msg:
        return ("OpenAI rate/quota limit (429). Usually an empty billing balance — "
                "check platform.openai.com/settings/organization/billing.")
    if name == "NotFoundError" or "model_not_found" in msg or "does not exist" in msg:
        return (f"Model '{MODEL}' is not available on this key. Set "
                f"CHATGPT_MONITOR_MODEL in .env to one you have access to.")
    return ""


def _dry_run(client) -> None:
    """One live call, printed raw — to verify the citation shape before trusting a full run."""
    q = build_questions("en")[0]
    print(f"🔬 DRY-RUN · model={MODEL}\n   Q: {q}\n")
    try:
        cited, mentioned, domains = ask(client, q)
    except Exception as e:
        reason = _fatal_reason(e)
        print(f"   ✗ {reason or str(e)[:200]}")
        return
    print(f"   cited={cited}  mentioned={mentioned}")
    print(f"   domains: {domains}")
    if not domains:
        print("\n   ⚠️  No citation domains extracted. Either the answer used no "
              "sources, or the annotation shape changed — inspect the raw payload "
              "before trusting a full run.")


def main() -> None:
    force = "--force" in sys.argv
    if not API_KEY:
        print("   ChatGPT GEO: OPENAI_API_KEY missing — skipping")
        return
    try:
        from openai import OpenAI
    except ImportError:
        print("   ChatGPT GEO: openai SDK missing — pip install openai")
        return

    client = OpenAI(api_key=API_KEY)

    if "--dry-run" in sys.argv:
        _dry_run(client)
        return

    hist = load_json(HISTORY, [])
    if not gate_ok(hist, force):
        print("   ChatGPT GEO: sampled <7 days ago — nothing to do")
        return

    by_market, all_cited, all_ment, all_q, calls = {}, 0, 0, 0, 0
    for lang in GEO_MARKETS:
        questions = build_questions(lang)
        print(f"💬 ChatGPT GEO [{lang}] — {len(questions)} native questions")
        details, cited_n, ment_n = [], 0, 0
        for q in questions:
            try:
                cited, mentioned, domains = ask(client, q)
            except Exception as e:
                # Config-level failures (dead key, no quota, wrong model) affect
                # every remaining question — stop instead of repeating the same
                # error 40 times and burying the cause.
                fatal = _fatal_reason(e)
                if fatal:
                    print(f"   ✗ {fatal}")
                    print("   → nothing recorded; the baseline stays untouched.")
                    return
                print(f"   ⚠️  '{q[:40]}': {str(e)[:120]}")
                continue
            calls += 1
            cited_n += int(cited)
            ment_n += int(mentioned)
            details.append({"question": q, "velluto_cited": cited,
                            "velluto_mentioned": mentioned, "top_domains": domains[:5]})
            print(f"   {'🟢' if cited else ('🟡' if mentioned else '⚪')} [{lang}] {q[:56]}")
            time.sleep(1)
        if details:
            by_market[lang] = {"questions": len(details), "velluto_cited": cited_n,
                               "velluto_mentioned": ment_n,
                               "rate": round(cited_n / len(details) * 100, 1),
                               "details": details}
            all_cited += cited_n
            all_ment += ment_n
            all_q += len(details)

    if not all_q:
        print("   ChatGPT GEO: no successful queries — not recording")
        return

    entry = {"date": dt.date.today().isoformat(), "model": MODEL,
             "questions": all_q, "velluto_cited": all_cited,
             "velluto_mentioned": all_ment,
             "rate": round(all_cited / all_q * 100, 1),
             "by_market": by_market}
    hist.append(entry)
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(hist[-52:], f, ensure_ascii=False, indent=1)

    mkt = " · ".join(f"{k}:{v['velluto_cited']}/{v['questions']}" for k, v in by_market.items())
    print(f"   ✓ Velluto cited {all_cited}/{all_q} ({entry['rate']}%) — {mkt}")
    print(f"     (+{all_ment} brand mentions without a source link)")
    print(f"     ~{calls} web-search calls this run — check billing if it looks off")


if __name__ == "__main__":
    main()
