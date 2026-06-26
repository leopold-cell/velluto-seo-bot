"""
GEO monitor — turns AI-Overview citation snapshots into a dated GEO-KPI time
series, mirroring the Scalify GEO-audit metrics (mention/citation rate, authority
share). Strategically the measurement layer the audit calls for: it makes the
+21-point path observable instead of a one-off snapshot.

Reuses research/ai_overview_monitor.py (Google AI Overview is the most accessible
LLM surface and, with Perplexity, the fastest GEO lever per the audit). Designed
to NEVER raise into the daily pipeline — on any missing input it records zeros.

Reads : data/processed/ai_overview_snapshots.json (refreshed here if possible)
Writes: geo_performance.json  {history: {date: record}, latest: date}
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from collections import Counter

VELLUTO_DOMAIN = "velluto-shop.com"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AIO_SNAPSHOTS = os.path.join(BASE_DIR, "data", "processed", "ai_overview_snapshots.json")
OUTPUT_PATH = os.path.join(BASE_DIR, "geo_performance.json")


def _load_aio_snapshots() -> dict:
    """Refresh AI-Overview snapshots if the monitor is runnable, else read the
    last file on disk. Both paths are best-effort — failures degrade to {}."""
    try:
        from research import ai_overview_monitor
        return ai_overview_monitor.run()
    except Exception as e:  # noqa: BLE001 — pipeline must never break here
        print(f"   GEO: AIO monitor not runnable ({e}); reading last snapshot")
    try:
        with open(AIO_SNAPSHOTS, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _rate(num: int, denom: int) -> float:
    return round(100.0 * num / denom, 1) if denom else 0.0


def compute_record(aio: dict) -> dict:
    """Derive the GEO-KPI record for today from an AI-Overview snapshot."""
    aios = aio.get("ai_overviews") or []
    aio_serps = aio.get("total_with_aio", len(aios))
    velluto_cited = aio.get("velluto_cited", sum(1 for a in aios if a.get("velluto_cited")))
    competitor_cited = aio.get("competitor_cited", sum(1 for a in aios if a.get("competitor_cited")))
    velluto_gap = sum(1 for a in aios if a.get("velluto_gap"))

    # Authority-domain share across every cited source (audit's authority view).
    domain_counts: Counter[str] = Counter()
    for a in aios:
        for c in (a.get("cited_sources") or []):
            d = (c.get("domain") or "").strip()
            if d:
                domain_counts[d] += 1
    total_citations = sum(domain_counts.values())
    velluto_citations = domain_counts.get(VELLUTO_DOMAIN, 0)
    top_domains = [{"domain": d, "citations": n} for d, n in domain_counts.most_common(10)]

    return {
        "aio_serps":                aio_serps,
        "velluto_cited":            velluto_cited,
        "competitor_cited":         competitor_cited,
        "velluto_gap":              velluto_gap,
        "velluto_citation_rate":    _rate(velluto_cited, aio_serps),
        "competitor_citation_rate": _rate(competitor_cited, aio_serps),
        "total_citations":          total_citations,
        "velluto_citations":        velluto_citations,
        "owned_citation_share":     _rate(velluto_citations, total_citations),
        "top_cited_domains":        top_domains,
    }


def run() -> dict:
    aio = _load_aio_snapshots()
    record = compute_record(aio)
    today = _dt.date.today().isoformat()

    try:
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            store = json.load(f)
    except Exception:
        store = {}
    history = store.get("history", {})
    history[today] = record
    # Keep a rolling year of daily records.
    if len(history) > 400:
        for k in sorted(history)[:-400]:
            history.pop(k, None)

    out = {"history": history, "latest": today}
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print(f"   ✓ GEO: AIO SERPs={record['aio_serps']} · "
          f"Velluto citation-rate={record['velluto_citation_rate']}% · "
          f"competitor={record['competitor_citation_rate']}% · "
          f"owned-share={record['owned_citation_share']}%")
    return out


if __name__ == "__main__":
    run()
