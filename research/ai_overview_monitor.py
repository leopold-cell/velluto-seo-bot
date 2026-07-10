"""
AI Overview monitor — reads serp_snapshots.json, detects AI Overview presence,
extracts cited domains, flags Velluto-gap if velluto-shop.com isn't cited.

Output: data/processed/ai_overview_snapshots.json
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from urllib.parse import urlparse

import config_loader
from research import serp_fetcher

VELLUTO_DOMAIN = "velluto-shop.com"
OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "processed", "ai_overview_snapshots.json",
)


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def _extract_citations(ai_overview: dict) -> list[dict]:
    """DataForSEO AI Overview items have nested 'items' with 'references' on each.
    Return [{domain, url, title}]."""
    out: list[dict] = []
    if not ai_overview:
        return out
    refs = ai_overview.get("references") or []
    for r in refs:
        url = r.get("url") or ""
        if url:
            out.append({
                "domain": _domain(url),
                "url":    url,
                "title":  r.get("title") or "",
                "source": r.get("source") or "",
            })
    # Also check nested .items[].references in case DFS shape varies
    for sub in (ai_overview.get("items") or []):
        for r in (sub.get("references") or []):
            url = r.get("url") or ""
            if url and not any(x["url"] == url for x in out):
                out.append({
                    "domain": _domain(url),
                    "url":    url,
                    "title":  r.get("title") or "",
                    "source": r.get("source") or "",
                })
    return out


def run() -> dict:
    serp = serp_fetcher.load_latest()
    if not serp or not serp.get("snapshots"):
        result = {"date": _dt.date.today().isoformat(), "ai_overviews": [],
                  "serps_scanned": 0,
                  "total_with_aio": 0, "velluto_cited": 0, "competitor_cited": 0}
        _save(result)
        print("   AIO: no SERP snapshot to parse")
        return result

    forbidden = config_loader.forbidden_outbound_domains()  # set of competitor domains
    aios = []
    total_with_aio   = 0
    velluto_cited    = 0
    competitor_cited = 0

    for snap in serp["snapshots"]:
        ai = snap.get("ai_overview")
        if not ai:
            continue
        total_with_aio += 1
        citations = _extract_citations(ai)
        cited_domains = {c["domain"] for c in citations}
        v_cited = VELLUTO_DOMAIN in cited_domains
        c_cited = bool(cited_domains & forbidden)
        if v_cited:
            velluto_cited += 1
        if c_cited:
            competitor_cited += 1

        # Summary text — DataForSEO sometimes nests as `text` or as items[].text
        summary_text = ai.get("text") or ""
        if not summary_text:
            parts = []
            for sub in (ai.get("items") or []):
                if sub.get("text"):
                    parts.append(sub["text"])
            summary_text = " ".join(parts).strip()

        aios.append({
            "market":              snap["market"],
            "keyword":             snap["keyword"],
            "ai_overview_present": True,
            "ai_overview_summary": (summary_text[:500] + "…") if len(summary_text) > 500 else summary_text,
            "cited_sources":       citations,
            "velluto_cited":       v_cited,
            "competitor_cited":    c_cited,
            "velluto_gap":         not v_cited and bool(citations),
        })

    result = {
        "date":             _dt.date.today().isoformat(),
        "ai_overviews":     aios,
        "serps_scanned":    len(serp["snapshots"]),
        "total_with_aio":   total_with_aio,
        "velluto_cited":    velluto_cited,
        "competitor_cited": competitor_cited,
    }
    _save(result)
    print(f"   ✓ AIO: {total_with_aio} SERPs with AI Overview "
          f"(Velluto cited: {velluto_cited}, competitor cited: {competitor_cited})")
    return result


def _save(payload: dict) -> None:
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    print(json.dumps({k: v for k, v in run().items() if k != "ai_overviews"}, indent=2))
