"""
Hermes experiment R1 — is the AI-visibility gap actually measurable?

THE QUESTION THIS ANSWERS
-------------------------
The whole Hermes business rests on one claim: "we can tell you whether AI
answers cite you". If ChatGPT/Perplexity answers swing so much run to run that
"not cited" is just noise, then the report is not a measurement, it has no
authority, and the product does not exist. Everything downstream is wasted work.

So this is the gate. Run it BEFORE building anything else.

HOW TO USE IT
-------------
Record a session on three DIFFERENT days (variance within a day understates it):

    python3 scripts/hermes_r1_variance.py --run
    # ... next day ...
    python3 scripts/hermes_r1_variance.py --run
    # ... next day ...
    python3 scripts/hermes_r1_variance.py --run --report

Then read the verdict:

    python3 scripts/hermes_r1_variance.py --report

STABILITY is the share of (engine, question, brand) triples whose cited/not
verdict was UNANIMOUS across sessions. Read it as:

    >= 85%   strong — the gap is a real, reportable metric
    70-85%   usable — report only brands stable across >=2 sessions
    < 70%    FAIL — do not sell this as a measurement. Fall back to Google
             AI Overviews via DataForSEO, which is far more deterministic.

Cost: one probe per (question x engine) scores every brand at once, so a
10-question session across both engines is ~20 calls, roughly $0.05-0.15.
Credentials are optional: an engine without a key is skipped, not an error.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"), override=True)
except Exception:
    pass

from ops import aiprobe                       # noqa: E402
from ops.aiprobe import Brand                 # noqa: E402
from ops.state import load_json, save_json    # noqa: E402

HISTORY_PATH = os.path.join(ROOT, "data", "hermes", "r1_variance.json")

# Default probe set: DTC cycling eyewear. Deliberately Velluto's own category so
# you can eyeball the answers against ground truth you already know — if the
# probe says something you know is wrong, that is the experiment failing early.
DEFAULT_BRANDS = [
    Brand(key="velluto",   domain="velluto-shop.com",   aliases=("velluto",)),
    Brand(key="oakley",    domain="oakley.com",         aliases=("oakley",)),
    Brand(key="100percent", domain="100percent.com",    aliases=("100%", "ride100")),
    Brand(key="rudyproject", domain="rudyproject.com",  aliases=("rudy project",)),
    Brand(key="poc",       domain="pocsports.com",      aliases=("poc sports",)),
]

DEFAULT_QUESTIONS = [
    "What are the best road cycling sunglasses in 2026?",
    "Which cycling glasses offer the best value for money?",
    "Best photochromic cycling sunglasses for road riding",
    "What cycling sunglasses do pro cyclists wear?",
    "Affordable alternatives to Oakley cycling glasses",
    "Best cycling sunglasses for small faces",
    "Which cycling glasses have the best lens clarity?",
    "Top rated cycling eyewear brands 2026",
    "Best sunglasses for gravel riding",
    "Cycling glasses with interchangeable lenses — which brand is best?",
]


def _load_config(path: str | None) -> tuple[list[Brand], list[str]]:
    """Optional JSON config: {"brands": [{"key","domain","aliases"}], "questions": [...]}."""
    if not path:
        return DEFAULT_BRANDS, DEFAULT_QUESTIONS
    cfg = load_json(path, {})
    brands = [Brand(key=b["key"], domain=b.get("domain", ""),
                    aliases=tuple(b.get("aliases", []))) for b in cfg.get("brands", [])]
    questions = list(cfg.get("questions", []))
    return (brands or DEFAULT_BRANDS), (questions or DEFAULT_QUESTIONS)


def run_session(brands: list[Brand], questions: list[str],
                engines: list[str], dry_run: bool) -> dict:
    """Probe every (question x engine) once and record who was cited."""
    session = {
        "started": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "date": _dt.date.today().isoformat(),
        "engines": engines,
        "brands": [b.key for b in brands],
        "questions": questions,
        "results": [],
    }
    if dry_run:
        print(f"🔬 DRY-RUN — would probe {len(questions)} question(s) "
              f"x {len(engines)} engine(s) = {len(questions) * len(engines)} calls")
        for q in questions[:3]:
            print(f"   Q: {q}")
        print("   (run with --run to execute)")
        return session

    total = len(questions) * len(engines)
    n = 0
    for q in questions:
        for eng in engines:
            n += 1
            res = aiprobe.probe(eng, q, brands)
            if res is None:
                print(f"   [{n}/{total}] {eng}: skipped (no API key)")
                continue
            if res.error:
                print(f"   [{n}/{total}] {eng}: ERROR {res.error}")
                session["results"].append(res.to_dict())
                continue
            cited = res.cited_keys()
            print(f"   [{n}/{total}] {eng}: {q[:52]:<52} → "
                  f"{', '.join(cited) if cited else '(none of our brands)'}")
            session["results"].append(res.to_dict())
    return session


def _verdicts(history: list[dict]) -> dict[tuple, list[bool]]:
    """(engine, question, brand) -> [cited?] one entry per session that asked it."""
    out: dict[tuple, list[bool]] = defaultdict(list)
    for session in history:
        for r in session.get("results", []):
            if r.get("error"):
                continue
            for brand_key, v in (r.get("brands") or {}).items():
                out[(r["engine"], r["question"], brand_key)].append(bool(v.get("cited")))
    return out


def report(history: list[dict]) -> int:
    """Print the stability verdict. Returns a shell exit code."""
    sessions = [s for s in history if s.get("results")]
    if len(sessions) < 2:
        print(f"\n⚠️  Only {len(sessions)} usable session(s) recorded. "
              "Run --run on at least 2 different days before judging stability.")
        return 0

    days = sorted({s.get("date", "?") for s in sessions})
    verdicts = _verdicts(history)
    repeated = {k: v for k, v in verdicts.items() if len(v) >= 2}
    if not repeated:
        print("\n⚠️  No (engine, question, brand) triple was probed twice — "
              "did the question set change between sessions?")
        return 0

    unanimous = [k for k, v in repeated.items() if all(v) or not any(v)]
    stability = len(unanimous) / len(repeated)

    # Per-engine breakdown: they usually differ a lot, and that changes the plan.
    per_engine: dict[str, list[bool]] = defaultdict(list)
    for (eng, _q, _b), v in repeated.items():
        per_engine[eng].append(all(v) or not any(v))

    print("\n" + "=" * 66)
    print(f"R1 STABILITY REPORT — {len(sessions)} sessions on {len(days)} day(s): "
          f"{', '.join(days)}")
    print("=" * 66)
    for eng, flags in sorted(per_engine.items()):
        pct = 100 * sum(flags) / len(flags)
        print(f"  {eng:<12} {pct:5.1f}% stable  ({sum(flags)}/{len(flags)} triples unanimous)")
    print(f"  {'OVERALL':<12} {100 * stability:5.1f}% stable  "
          f"({len(unanimous)}/{len(repeated)} triples unanimous)")

    # The flappers are the interesting part — they are what a client would catch.
    flappy = [(k, v) for k, v in repeated.items() if not (all(v) or not any(v))]
    if flappy:
        print(f"\n  Unstable triples ({len(flappy)}) — a client WILL notice these:")
        for (eng, q, b), v in flappy[:10]:
            seq = " → ".join("YES" if x else "no" for x in v)
            print(f"    {eng:<11} {b:<12} {seq:<20} {q[:44]}")
        if len(flappy) > 10:
            print(f"    ... and {len(flappy) - 10} more")

    print("\n  VERDICT: ", end="")
    if stability >= 0.85:
        print("✅ STRONG — the gap is a real, reportable metric. Proceed with Hermes.")
        return 0
    if stability >= 0.70:
        print("🟡 USABLE — report only brands stable across >=2 sessions.")
        print("           Build the probe to require 2 agreeing runs before it claims a gap.")
        return 0
    print("❌ FAIL — do not sell this as a measurement.")
    print("           Fall back to Google AI Overviews via DataForSEO (far more")
    print("           deterministic), or drop the 'monitoring' framing entirely.")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="probe now and append a session")
    ap.add_argument("--report", action="store_true", help="print the stability verdict")
    ap.add_argument("--config", help="JSON file with custom brands/questions")
    ap.add_argument("--engines", default="perplexity,chatgpt",
                    help="comma-separated (default: perplexity,chatgpt)")
    ap.add_argument("--limit", type=int, help="use only the first N questions")
    args = ap.parse_args()

    if not (args.run or args.report):
        ap.print_help()
        return 0

    brands, questions = _load_config(args.config)
    if args.limit:
        questions = questions[:args.limit]
    engines = [e.strip() for e in args.engines.split(",") if e.strip()]

    history = load_json(HISTORY_PATH, [])
    if not isinstance(history, list):
        history = []

    if args.run:
        have = {"perplexity": bool(os.getenv("PERPLEXITY_API_KEY")),
                "chatgpt": bool(os.getenv("OPENAI_API_KEY"))}
        missing = [e for e in engines if not have.get(e, False)]
        if missing:
            print(f"⚠️  No API key for: {', '.join(missing)} — those will be skipped.")
        usable = [e for e in engines if have.get(e, False)]
        if not usable:
            print("❌ No engine has credentials. Set PERPLEXITY_API_KEY and/or "
                  "OPENAI_API_KEY (they live in .env on the VPS).")
            return 1

        print(f"🔬 R1 session — {len(questions)} questions x {len(usable)} engine(s) "
              f"x {len(brands)} brands scored per answer")
        session = run_session(brands, questions, usable, dry_run=False)
        history.append(session)
        save_json(HISTORY_PATH, history)
        print(f"\n💾 Session saved → {os.path.relpath(HISTORY_PATH, ROOT)} "
              f"({len(history)} total)")

    if args.report:
        return report(history)
    return 0


if __name__ == "__main__":
    sys.exit(main())
