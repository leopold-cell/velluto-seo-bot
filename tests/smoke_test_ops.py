"""
Smoke test for the shared ops/ package (offline, no credentials).

Two jobs:
  1. Prove the review/_common.py extraction was behaviour-preserving — the
     re-exports must be the SAME objects and the Velluto constants unchanged.
  2. Cover the new mechanisms: atomic state IO, the self-gating interval check,
     and the DataForSEO per-project spend ledger.

Run: python3 tests/smoke_test_ops.py
"""
import datetime as _dt
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops import aiprobe, dataforseo, llm, state, vision
from review import _common, ui_audit

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import hermes_r1_variance as r1  # noqa: E402

failures = []


def check(name, cond):
    print(("✅" if cond else "❌") + f" {name}")
    if not cond:
        failures.append(name)


# ── 1. extraction is behaviour-preserving ───────────────────────────────────
print("\n=== re-export identity (regression proof for the ops/ extraction) ===")
check("_common.HAIKU is ops.llm.HAIKU", _common.HAIKU is llm.HAIKU)
check("_common.SONNET is ops.llm.SONNET", _common.SONNET is llm.SONNET)
check("HAIKU id unchanged", llm.HAIKU == "claude-haiku-4-5-20251001")
check("SONNET id unchanged", llm.SONNET == "claude-sonnet-4-6")
check("have_anthropic is shared", _common.have_anthropic is llm.have_anthropic)
check("parse_json_block is shared", _common.parse_json_block is llm.parse_json_block)
check("http_get is shared", _common.http_get is llm.http_get)
check("ui_audit.playwright_available delegates",
      ui_audit.playwright_available() == vision.playwright_available())
check("ui_audit.VIEWPORTS unchanged", ui_audit.VIEWPORTS == {"mobile": (390, 844),
                                                             "desktop": (1440, 900)})

print("\n=== Velluto constants must NOT have moved ===")
check("SITE unchanged", _common.SITE == "https://velluto-shop.com")
check("BLOG_HANDLE unchanged", _common.BLOG_HANDLE == "velluto-the-magazine")
check("SHOP_LOCALES intact (10 locales)", len(_common.SHOP_LOCALES) == 10
      and _common.SHOP_LOCALES[0] == "de")
check("_log_cost still local to review", callable(_common._log_cost))

print("\n=== guarded degradation without a key ===")
_saved_key = os.environ.pop("ANTHROPIC_API_KEY", None)
try:
    check("have_anthropic() False without key", llm.have_anthropic() is False)
    check("ops.llm.complete() -> '' without key", llm.complete("s", "u") == "")
    check("_common.complete() -> '' without key", _common.complete("s", "u") == "")
finally:
    if _saved_key is not None:
        os.environ["ANTHROPIC_API_KEY"] = _saved_key

print("\n=== parse_json_block ===")
check("fenced json", llm.parse_json_block('```json\n{"a": 1}\n```') == {"a": 1})
check("bare json", llm.parse_json_block('{"a": 1}') == {"a": 1})
check("json embedded in prose", llm.parse_json_block('Sure!\n{"a": 1}\nDone.') == {"a": 1})
check("array", llm.parse_json_block("[1, 2]") == [1, 2])
check("garbage -> None", llm.parse_json_block("not json at all") is None)
check("empty -> None", llm.parse_json_block("") is None)

print("\n=== vision helpers ===")
check("as_image_blocks shape",
      vision.as_image_blocks({"mobile": "AAA"}) ==
      [{"media_type": "image/png", "data": "AAA"}])
check("as_image_blocks empty", vision.as_image_blocks({}) == [])

# ── 2. state: atomic IO + self-gating ───────────────────────────────────────
print("\n=== state IO ===")
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "nested", "s.json")
    state.save_json(p, {"a": 1, "when": _dt.date(2026, 1, 2)})
    check("save_json creates parent dirs", os.path.exists(p))
    check("round-trip", state.load_json(p)["a"] == 1)
    check("date serialised via default=str", state.load_json(p)["when"] == "2026-01-02")
    check("no temp files left behind",
          [f for f in os.listdir(os.path.dirname(p)) if f.startswith(".tmp-")] == [])

    missing = os.path.join(td, "nope.json")
    check("missing file -> {}", state.load_json(missing) == {})
    check("missing file -> explicit default", state.load_json(missing, []) == [])

    corrupt = os.path.join(td, "bad.json")
    open(corrupt, "w").write('{"truncated": ')
    check("corrupt file -> default, no raise", state.load_json(corrupt, {"fb": 1}) == {"fb": 1})

print("\n=== gate_ok (self-gating convention) ===")
with tempfile.TemporaryDirectory() as td:
    g = os.path.join(td, "gate.json")
    check("no state -> run", state.gate_ok(g, 28)[0] is True)

    state.mark_run(g)
    check("ran today -> skip", state.gate_ok(g, 28)[0] is False)
    check("--force overrides", state.gate_ok(g, 28, force=True)[0] is True)

    state.save_json(g, {"last_run": (_dt.date.today() - _dt.timedelta(days=40)).isoformat()})
    check("40d ago, interval 28 -> run", state.gate_ok(g, 28)[0] is True)

    state.save_json(g, {"last_run": (_dt.date.today() - _dt.timedelta(days=8)).isoformat()})
    check("8d ago, interval 28 -> skip", state.gate_ok(g, 28)[0] is False)
    check("8d ago, interval 7 -> run", state.gate_ok(g, 7)[0] is True)

    state.save_json(g, {"last_run": "not-a-date"})
    check("unreadable date -> run (never block forever)", state.gate_ok(g, 28)[0] is True)

    state.save_json(g, {"last_run": "2020-01-01", "keep": "me"})
    state.mark_run(g, extra_field=7)
    reloaded = state.load_json(g)
    check("mark_run preserves other keys", reloaded.get("keep") == "me")
    check("mark_run writes today", reloaded["last_run"] == _dt.date.today().isoformat())
    check("mark_run stores extras", reloaded.get("extra_field") == 7)

# ── 3. DataForSEO shared spend ledger ───────────────────────────────────────
print("\n=== DataForSEO ledger: per-project caps ===")
_orig_ledger = dataforseo.LEDGER_PATH
_orig_cap = os.environ.get("HERMES_DATAFORSEO_TASK_CAP")
with tempfile.TemporaryDirectory() as td:
    dataforseo.LEDGER_PATH = os.path.join(td, "spend.json")
    try:
        check("known unit price: SERP",
              dataforseo.unit_usd("serp/google/organic/live/advanced") == 0.002)
        check("known unit price: search_volume is the expensive one",
              dataforseo.unit_usd("keywords_data/google_ads/search_volume/live") == 0.05)
        check("unknown path falls back to a default", dataforseo.unit_usd("who/knows") > 0)

        # Uncapped project (velluto): always granted, still recorded.
        os.environ.pop("VELLUTO_DATAFORSEO_TASK_CAP", None)
        check("uncapped project has no cap", dataforseo.project_cap("velluto") is None)
        granted, _ = dataforseo.reserve("velluto", 30, "serp/google/organic/live/advanced")
        check("uncapped: full grant", granted == 30)
        tasks, usd = dataforseo.spent_today("velluto")
        check("uncapped: spend recorded", tasks == 30 and abs(usd - 0.06) < 1e-9)

        # Capped project (hermes): this is the guard that protects the shared balance.
        os.environ["HERMES_DATAFORSEO_TASK_CAP"] = "10"
        check("capped project reads its cap", dataforseo.project_cap("hermes") == 10)
        g1, _ = dataforseo.reserve("hermes", 4, "serp/google/organic/live/advanced")
        check("capped: first grant full", g1 == 4)
        g2, _ = dataforseo.reserve("hermes", 20, "serp/google/organic/live/advanced")
        check("capped: partial grant up to the cap", g2 == 6)
        g3, why = dataforseo.reserve("hermes", 5, "serp/google/organic/live/advanced")
        check("capped: exhausted -> 0", g3 == 0)
        check("capped: reason explains why", "cap reached" in why)

        check("velluto unaffected by hermes' cap",
              dataforseo.spent_today("velluto")[0] == 30)
        check("hermes stopped exactly at its cap",
              dataforseo.spent_today("hermes")[0] == 10)
        check("summary names both projects",
              "hermes" in dataforseo.summary() and "velluto" in dataforseo.summary())

        # A new day resets the counters.
        led = json.load(open(dataforseo.LEDGER_PATH))
        led["date"] = "2020-01-01"
        json.dump(led, open(dataforseo.LEDGER_PATH, "w"))
        check("new day resets counters", dataforseo.spent_today("hermes")[0] == 0)
        check("new day re-grants", dataforseo.reserve("hermes", 3, "on_page/instant_pages")[0] == 3)

        # No credentials -> no HTTP attempt, no spend.
        _lo = os.environ.pop("DATAFORSEO_LOGIN", None)
        _pw = os.environ.pop("DATAFORSEO_PASSWORD", None)
        try:
            check("post() without credentials -> None",
                  dataforseo.post("serp/google/organic/live/advanced", [{}]) is None)
            check("post() without credentials spends nothing",
                  dataforseo.spent_today("velluto")[0] == 0)
        finally:
            if _lo is not None:
                os.environ["DATAFORSEO_LOGIN"] = _lo
            if _pw is not None:
                os.environ["DATAFORSEO_PASSWORD"] = _pw
    finally:
        dataforseo.LEDGER_PATH = _orig_ledger
        if _orig_cap is None:
            os.environ.pop("HERMES_DATAFORSEO_TASK_CAP", None)
        else:
            os.environ["HERMES_DATAFORSEO_TASK_CAP"] = _orig_cap

# ── 4. aiprobe: who was cited, and who wasn't ───────────────────────────────
print("\n=== aiprobe: domain parsing ===")
check("strips www", aiprobe.domain_of("https://www.oakley.com/x/y") == "oakley.com")
check("keeps subdomain", aiprobe.domain_of("https://shop.example.co.uk/a") == "shop.example.co.uk")
check("garbage -> ''", aiprobe.domain_of(None) == "")
check("empty -> ''", aiprobe.domain_of("") == "")

print("\n=== aiprobe: cited vs mentioned (different products, must not conflate) ===")
_v = aiprobe.Brand(key="velluto", domain="velluto-shop.com", aliases=("velluto",))
_o = aiprobe.Brand(key="oakley", domain="oakley.com", aliases=("oakley",))
_scored = aiprobe._score_brands(
    [_v, _o],
    urls=["https://www.oakley.com/sunglasses"],
    text="Consider Oakley, or Velluto for better value.",
)
check("cited when a source URL matches", _scored["oakley"]["cited"] is True)
check("cited is not also 'mentioned'", _scored["oakley"]["mentioned"] is False)
check("named in prose only -> mentioned", _scored["velluto"]["mentioned"] is True)
check("prose mention is NOT a citation", _scored["velluto"]["cited"] is False)

_none = aiprobe._score_brands([_v], urls=["https://poc.com"], text="Try POC.")
check("absent brand: neither cited nor mentioned",
      _none["velluto"] == {"cited": False, "mentioned": False})

_res = aiprobe.ProbeResult(engine="e", question="q", asked_at="t",
                           brands={"a": {"cited": True}, "b": {"cited": False}})
check("cited_keys lists only cited brands", _res.cited_keys() == ["a"])
check("ProbeResult is JSON-serialisable", isinstance(_res.to_dict(), dict))

print("\n=== aiprobe: guarded degradation ===")
_pk = os.environ.pop("PERPLEXITY_API_KEY", None)
_ok = os.environ.pop("OPENAI_API_KEY", None)
try:
    check("perplexity without key -> None", aiprobe.probe_perplexity("q", [_v]) is None)
    check("chatgpt without key -> None", aiprobe.probe_chatgpt("q", [_v]) is None)
finally:
    if _pk is not None:
        os.environ["PERPLEXITY_API_KEY"] = _pk
    if _ok is not None:
        os.environ["OPENAI_API_KEY"] = _ok

try:
    aiprobe.probe("bing", "q", [_v])
    check("unknown engine raises", False)
except ValueError:
    check("unknown engine raises", True)

# ── 5. R1 experiment: the stability math that gates the whole plan ──────────
print("\n=== R1 variance: stability math ===")


def _session(day, per_brand_cited):
    """per_brand_cited: {question: {brand: cited_bool}}"""
    return {"date": day, "results": [
        {"engine": "perplexity", "question": q, "error": "",
         "brands": {b: {"cited": c} for b, c in brands.items()}}
        for q, brands in per_brand_cited.items()]}


_stable = [_session("2026-08-11", {"q1": {"velluto": False, "oakley": True}}),
           _session("2026-08-12", {"q1": {"velluto": False, "oakley": True}})]
check("identical sessions -> 100% stable", r1.report(_stable) == 0)
check("verdicts group by (engine, question, brand)", len(r1._verdicts(_stable)) == 2)

_flappy = [_session("2026-08-11", {"q1": {"velluto": False, "oakley": True}}),
           _session("2026-08-12", {"q1": {"velluto": True, "oakley": False}})]
_v2 = r1._verdicts(_flappy)
check("total disagreement -> 0% stable, exit 1", r1.report(_flappy) == 1)
check("both triples recorded twice", all(len(v) == 2 for v in _v2.values()))

check("single session -> no verdict, exit 0", r1.report(_stable[:1]) == 0)
check("errored results are excluded",
      r1._verdicts([{"date": "d", "results": [
          {"engine": "e", "question": "q", "error": "boom", "brands": {"a": {"cited": True}}}]}]) == {})

print()
if failures:
    print(f"❌ {len(failures)} FAILED:")
    for f in failures:
        print(f"   - {f}")
    sys.exit(1)
print("✅ ALL PASSED")
