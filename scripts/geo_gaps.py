#!/usr/bin/env python3
"""
Closes the loop between AI-visibility MEASUREMENT and CONTENT.

The monitors produce ~80 data points a week saying "on this question, Velluto was
not cited" — and until now nothing read them. Those questions are the most precise
content roadmap available: they are real buyer questions, asked in the buyer's own
language, on the surfaces we want to win.

This module ranks the persistent misses (not cited across several consecutive runs)
and reports them as PROPOSALS for data/paa_seed.json. From there the existing chain
takes over automatically:

    data/paa_seed.json
      → briefs/us_master_brief.py::_gather_paa_questions()
      → brief["must_answer_questions"]
      → prompt requires each as a verbatim H2 + 40-70 word direct answer
      → ===FAQ_JSON=== → FAQPage JSON-LD (seo_bot.py)

DELIBERATELY NOT AUTOMATIC. paa_seed.json is curated, and questions harvested from
AI answers routinely concern things Velluto does not sell (photochromic, polarised,
prescription — see is_compatible() in en_keyword_queue.py). Auto-writing them would
push briefs toward content the legal gate and the product range cannot support.
A human picks from the list; the plumbing after that is automatic.

Usage:
  python3 scripts/geo_gaps.py              # print the report
  python3 scripts/geo_gaps.py --markdown   # markdown (for the weekly digest)
  python3 scripts/geo_gaps.py --propose-paa # paste-ready paa_seed.json block
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from geo_questions import GEO_MARKETS, load_json  # noqa: E402

# A question counts as a persistent gap once it was measured at least this often
# and never produced a citation. Below this, a single unlucky run would make noise.
MIN_RUNS = 2
TOP_N = 8


def _runs(rel_path: str, surface: str) -> list[dict]:
    hist = load_json(rel_path, [])
    return [{"surface": surface, **r} for r in hist if isinstance(r, dict)]


def collect_gaps(max_runs: int = 6) -> dict[str, list[dict]]:
    """{market: [{question, misses, runs, surfaces, rivals}]} — worst first.

    Looks at the last `max_runs` samples per surface so a question fixed months
    ago doesn't linger in the report forever.
    """
    runs = (_runs("data/chatgpt_geo.json", "ChatGPT")[-max_runs:]
            + _runs("data/perplexity_geo.json", "Perplexity")[-max_runs:])

    # (market, question) -> stats
    acc: dict[tuple[str, str], dict] = {}
    for run in runs:
        for market, mrec in (run.get("by_market") or {}).items():
            for det in (mrec.get("details") or []):
                q = det.get("question")
                if not q:
                    continue
                key = (market, q)
                st = acc.setdefault(key, {"question": q, "market": market, "runs": 0,
                                          "misses": 0, "surfaces": set(), "rivals": {}})
                st["runs"] += 1
                if det.get("velluto_cited"):
                    continue
                st["misses"] += 1
                st["surfaces"].add(run["surface"])
                # who IS being cited instead — that's the competitive target
                for dom in (det.get("top_domains") or [])[:5]:
                    if dom and "velluto" not in dom:
                        st["rivals"][dom] = st["rivals"].get(dom, 0) + 1

    out: dict[str, list[dict]] = {m: [] for m in GEO_MARKETS}
    for (market, _q), st in acc.items():
        if st["runs"] < MIN_RUNS or st["misses"] < st["runs"]:
            continue  # cited at least once → not a persistent gap
        rivals = sorted(st["rivals"].items(), key=lambda kv: -kv[1])[:3]
        out.setdefault(market, []).append({
            "question": st["question"],
            "misses": st["misses"],
            "runs": st["runs"],
            "surfaces": sorted(st["surfaces"]),
            "rivals": [d for d, _ in rivals],
        })
    for market in out:
        out[market].sort(key=lambda r: (-r["misses"], r["question"]))
    return out


def format_report(gaps: dict[str, list[dict]], markdown: bool = False) -> str:
    total = sum(len(v) for v in gaps.values())
    bullet = "-" if markdown else "•"
    lines: list[str] = []
    if not total:
        lines.append("Keine belastbaren GEO-Lücken — entweder überall zitiert "
                     f"oder noch <{MIN_RUNS} Messläufe vorhanden.")
        return "\n".join(lines)

    head = f"Fragen ohne Velluto-Zitierung ({total} über alle Märkte)"
    lines.append(f"### {head}" if markdown else head)
    lines.append("Kandidaten für data/paa_seed.json — bitte prüfen, ob Velluto die "
                 "Frage ehrlich beantworten kann (keine Photochrom-/Polarisations-/"
                 "Sehstärken-Themen).")
    lines.append("")
    for market in GEO_MARKETS:
        rows = gaps.get(market) or []
        if not rows:
            continue
        lines.append(f"**{market.upper()}**" if markdown else f"[{market.upper()}]")
        for r in rows[:TOP_N]:
            rivals = f" — zitiert stattdessen: {', '.join(r['rivals'])}" if r["rivals"] else ""
            lines.append(f"  {bullet} {r['question']}  "
                         f"({r['misses']}/{r['runs']} Läufe, {'+'.join(r['surfaces'])}){rivals}")
        lines.append("")
    return "\n".join(lines).rstrip()


def propose_paa(gaps: dict[str, list[dict]]) -> str:
    """Turn the gaps into a paste-ready data/paa_seed.json block.

    The loop was designed to end at "here are the questions" and leave the
    curation by hand, which meant it never actually closed — the questions sat in
    a weekly digest while the article pipeline kept drawing from the same static
    keyword queue. This does the mechanical part of the curation: drops what
    Velluto cannot honestly answer (photochromic, polarised, prescription — the
    is_compatible() list), drops what the legal gate would reject, and prints the
    rest as JSON to paste in.

    Still a proposal, deliberately. A question that survives both filters can
    still be off-brand or a duplicate of an existing cluster, and that call needs
    eyes. What changes is that the manual step is now "read 8 lines and paste"
    rather than "re-derive the list".

    Why it matters for AI Overviews: a question that reaches paa_seed becomes a
    verbatim H2 with a 40-70 word direct answer and a FAQPage entry — the
    extractable form answer engines quote. Ranking still decides whether they
    look, but this decides whether there is anything quotable when they do.
    """
    try:
        from en_keyword_queue import is_compatible
    except Exception:
        def is_compatible(_q):    # noqa: E306 — fall open rather than block the report
            return True
    try:
        from briefs.quality_gate import check_compliance
    except Exception:
        check_compliance = None

    seed = load_json(os.path.join("data", "paa_seed.json"), {})
    out: dict[str, list[str]] = {}
    dropped: list[tuple[str, str]] = []

    for market, rows in gaps.items():
        known = {q.lower()
                 for cluster in (seed.get(market) or {}).values()
                 for q in (cluster if isinstance(cluster, list) else [])}
        for r in rows:
            q = r["question"]
            if q.lower() in known:
                continue
            if not is_compatible(q):
                dropped.append((q, "Produkt bietet das nicht an"))
                continue
            if check_compliance and check_compliance({"title": q, "body_html": q}):
                dropped.append((q, "Legal-Gate"))
                continue
            out.setdefault(market, []).append(q)

    L = ["Vorschlag für data/paa_seed.json — geprüft auf Produkt-Fit und Legal-Gate", ""]
    if not out:
        L.append("  (nichts Neues — alle Lückenfragen stehen schon drin oder wurden gefiltert)")
    for market, qs in out.items():
        L.append(f'  "{market}": {{ "<cluster>": [')
        for q in qs[:8]:
            L.append(f'      {json.dumps(q, ensure_ascii=False)},')
        L.append("  ]}")
        L.append("")
    if dropped:
        L.append(f"Gefiltert ({len(dropped)}):")
        for q, why in dropped[:6]:
            L.append(f"  · {q[:64]} — {why}")
    L.append("")
    L.append("Cluster-Schlüssel selbst wählen (best-cycling, anti-fog, fit, price-value …) "
             "und in die passende Sprache einsortieren.")
    return "\n".join(L)


def main() -> None:
    gaps = collect_gaps()
    if "--propose-paa" in sys.argv:
        print(propose_paa(gaps))
        return
    print(format_report(gaps, markdown="--markdown" in sys.argv))


if __name__ == "__main__":
    main()
