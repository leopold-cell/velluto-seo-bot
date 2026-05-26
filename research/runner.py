"""
Phase 2 research runner — orchestrates all 5 research modules.

Each module is called inside its own try/except so one failure doesn't take
down the others. Returns a single dict containing all 5 outputs plus a
human-readable summary_line for the bot log.
"""
from __future__ import annotations

import traceback


def run_research_bundle() -> dict:
    out: dict = {}

    # Lazy imports — keeps `from research import runner` cheap when not used
    from research import (
        competitor_monitor,
        serp_fetcher,
        paa_extractor,
        ai_overview_monitor,
        gsc_fetcher,
    )

    # Order matters: SERP first → PAA and AIO parse its output.
    for name, mod in [
        ("serps",        serp_fetcher),
        ("paa",          paa_extractor),
        ("ai_overviews", ai_overview_monitor),
        ("competitors",  competitor_monitor),
        ("gsc",          gsc_fetcher),
    ]:
        try:
            out[name] = mod.run()
        except Exception as e:
            print(f"   ⚠️  research.{name} failed: {e}")
            traceback.print_exc()
            out[name] = {"error": str(e)}

    # Build a one-line summary
    serps_n     = len((out.get("serps")        or {}).get("snapshots", []))
    paa_total   =     (out.get("paa")          or {}).get("total_questions", 0)
    paa_high    =     (out.get("paa")          or {}).get("high_intent_questions", 0)
    aio_n       =     (out.get("ai_overviews") or {}).get("total_with_aio", 0)
    comp_new    =     (out.get("competitors")  or {}).get("total_new_urls", 0)
    gsc_strike  = len((out.get("gsc")          or {}).get("striking_distance_queries", []))

    out["summary_line"] = (
        f"{serps_n} SERPs | {paa_total} PAA ({paa_high} high) | "
        f"{aio_n} AIO | {comp_new} new comp URLs | {gsc_strike} striking-distance"
    )
    return out


if __name__ == "__main__":
    import json
    bundle = run_research_bundle()
    print("\n" + bundle["summary_line"])
    print("\nKeys:", list(bundle.keys()))
