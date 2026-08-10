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


def _aio_run() -> list[dict]:
    """Google AI Overviews, reshaped into the same {by_market: {details}} form.

    This surface was missing from the roadmap entirely, and it is the largest one
    we measure: ~115 AIO SERPs a day against 40 Perplexity questions a week. The
    monitor already records, per query, whether Velluto was cited and which
    domains were cited instead (research/ai_overview_monitor.py) — the data was
    there, nothing read it. With the citation rate sitting at 0.0% across ten
    consecutive days, this is the signal that matters most.

    Note the unit differs: AIO entries are KEYWORDS, not natural-language
    questions. They still belong in the same list — a keyword Google answers
    without citing us is exactly a topic we have nothing quotable for — but they
    read as search terms in the report, which is correct rather than a bug.
    """
    snap = load_json(os.path.join("data", "processed", "ai_overview_snapshots.json"), {})
    entries = snap.get("ai_overviews") or []
    if not entries:
        return []
    # AIO snapshots are keyed by SEARCH MARKET (us, gb, da, pl …) while paa_seed
    # and the monitors are keyed by LANGUAGE (en, de, nl, fr). Passing the market
    # through unmapped filed English keywords under "pl" and invented a "us"
    # bucket that no downstream consumer knows.
    MARKET_LANG = {"us": "en", "gb": "en", "uk": "en", "au": "en", "ca": "en",
                   "ie": "en", "at": "de", "ch": "de", "be": "nl"}
    by_market: dict[str, dict] = {}
    for e in entries:
        if not e.get("keyword"):
            continue
        market = (e.get("market") or "en").lower()[:2]
        market = MARKET_LANG.get(market, market)
        by_market.setdefault(market, {"details": []})["details"].append({
            "question": e["keyword"],
            "velluto_cited": bool(e.get("velluto_cited")),
            "top_domains": [c.get("domain", "") for c in (e.get("cited_sources") or [])][:5],
        })
    return [{"surface": "AI Overview", "date": snap.get("date", ""), "by_market": by_market}]


def collect_gaps(max_runs: int = 6) -> dict[str, list[dict]]:
    """{market: [{question, misses, runs, surfaces, rivals}]} — worst first.

    Looks at the last `max_runs` samples per surface so a question fixed months
    ago doesn't linger in the report forever.
    """
    runs = (_runs("data/chatgpt_geo.json", "ChatGPT")[-max_runs:]
            + _runs("data/perplexity_geo.json", "Perplexity")[-max_runs:]
            + _aio_run())

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
        # MIN_RUNS suppresses noise from a single unlucky sample, which is right
        # for the chat surfaces — a model can phrase one answer differently. An AI
        # Overview is not a sample: Google answered that query and listed its
        # sources, and we were not among them. One observation is the fact.
        # (The snapshot file only ever holds the latest run, so requiring two
        # would drop every AIO entry regardless.)
        floor = 1 if "AI Overview" in st["surfaces"] else MIN_RUNS
        if st["runs"] < floor or st["misses"] < st["runs"]:
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


# Question openers across the 11 shop languages — a paa_seed entry has to read as
# a question, because the prompt turns it into a verbatim H2 with a direct answer.
_Q_OPENERS = (
    "what", "which", "how", "why", "are", "is", "do", "does", "can", "should",
    "was", "welche", "welcher", "welches", "wie", "warum", "sind", "ist", "kann", "lohnt",
    "wat", "welke", "hoe", "waarom", "zijn", "kan",
    "quelle", "quelles", "quel", "quels", "comment", "pourquoi", "est", "les",
    "quale", "quali", "come", "perché", "sono",
    "qué", "cuál", "cuáles", "cómo", "por", "son",
    "vilken", "vilka", "hur", "varför", "är",
    "hvilken", "hvilke", "hvordan", "hvorfor", "er",
    "jaki", "jaka", "jakie", "czy", "ile",
    "qual", "quais", "como", "porque",
)


def _is_question(text: str) -> bool:
    """A paa_seed entry must be a real question, not a search keyword.

    The opener word alone is not enough: "are expensive cycling sunglasses worth
    it" opens with "are" and is a keyword, while every question in the curated
    bank ends with "?". Requiring the mark is what separates them — and it also
    keeps AI Overview entries out of paa_seed entirely, which is correct, since
    those are search terms and belong in the keyword queue.
    """
    t = (text or "").strip()
    if not t.endswith("?"):
        return False
    return t[0].isupper() or t.lower().split(" ")[0].strip("¿") in _Q_OPENERS


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
            # paa_seed entries become verbatim H2s with a 40-70 word answer, so
            # only question-shaped items belong here. AI Overview gaps are search
            # KEYWORDS ("beste fahrradbrille 2026") — real signal, wrong container;
            # they belong in the keyword queue and are listed separately below.
            if not _is_question(q):
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
    kw = sorted({r["question"] for rows in gaps.values() for r in rows
                 if "AI Overview" in r.get("surfaces", []) and not _is_question(r["question"])})
    if kw:
        L.append("Keywords aus den AI Overviews — gehören in die Keyword-Queue, nicht in paa_seed:")
        for k in kw[:10]:
            L.append(f"  · {k}")
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
