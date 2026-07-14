#!/usr/bin/env python3
"""
Velluto Content Retrofit — executes the daily report's "Optimierungs-Fokus"
on EXISTING articles, on a 28-day cycle (GSC needs that long to show effects).

Cycle (self-gated, runs as a daily run.sh step like blog_review):
  1. MEASURE  — for articles changed last cycle: GSC 28d before vs. 28d after
                (clicks, impressions, CTR, position) → improved/no_lift/regressed.
                Flags pages the CTR optimizer touched in the same window
                (attribution unclear).
  2. AUDIT    — current state of every bot article: word count, has <table>,
                has FAQPage schema → data/content_state.json (consumed by
                seo_optimizer insights + daily_report so they stop
                recommending what is already done).
  3. SELECT   — max 2 articles/cycle. Cycle 1 is seeded with the two known
                problems: comparison table for the Oakley-alternatives post,
                content expansion for the thin "best cycling glasses" post.
                Later cycles score by impressions × deficit. 56d cooldown per
                article; skips pages the CTR optimizer rewrote <14d ago.
  4. EXECUTE  — additive-only body changes (nothing is deleted):
                - "table":  comparison table (real Velluto product data,
                  competitor info as RANGES only) inserted before the FAQ.
                - "expand": 2-4 new <h2> sections answering the page's REAL
                  top queries, inserted before the FAQ. (+1.5-3k words)
                EN body updated via the proven backfill flow (PUT → digests →
                re-register); every locale gets the fragment ADAPTED and
                spliced into its EXISTING translation (titles/metas untouched).
  5. REPORT   — email summary: what changed now + what last cycle achieved.

Usage:  python3 content_retrofit.py [--dry-run] [--force]
"""
import datetime
import json
import os
import re
import sys

import requests
from anthropic import Anthropic
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "scripts"))
load_dotenv(dotenv_path=os.path.join(BASE, ".env"), override=True)

from ctr_optimizer import (_gsc_query, _gsc_token, fetch_page_queries,   # noqa: E402
                           STATE_PATH as CTR_STATE_PATH)
from seo_bot import (BLOG_ID, LOCALE_LANG_NAMES, SHOP_LOCALES,           # noqa: E402
                     SHOPIFY_HEADERS, SHOPIFY_STORE,
                     get_translatable_digests, register_shopify_translation)
from backfill_seo_cleanup import fetch_translations, put_body            # noqa: E402

STATE_PATH   = os.path.join(BASE, "data", "content_retrofit_state.json")
CONTENT_STATE_PATH = os.path.join(BASE, "data", "content_state.json")
SITE         = "https://velluto-shop.com"
INTERVAL_DAYS   = 28
COOLDOWN_DAYS   = 56     # 2 cycles per article
CTR_QUIET_DAYS  = 14     # don't touch pages the snippet optimizer just changed
MAX_PER_CYCLE   = 2
HAIKU  = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6"


DRY_RUN = "--dry-run" in sys.argv
FORCE   = "--force" in sys.argv

# Cycle-1 seeds: the two known problems from the report (resolved at runtime).
# The Oakley post gets table AND PAA-driven expansion in one pass — the SERP
# shows a large People-Also-Ask block for this cluster (see data/paa_seed.json).
SEEDS = [
    {"handle": "oakley-alternative-cycling-sunglasses-why-riders-switch", "action": "table+expand"},
    {"handle_prefix": "best-cycling", "action": "expand"},
]


# ── pure helpers (unit-testable) ─────────────────────────────────────────────

def word_count(html: str) -> int:
    return len(re.sub(r"<[^>]+>", " ", html or "").split())


def has_table(html: str) -> bool:
    return bool(re.search(r"<table\b", html or "", re.I))


def has_faq_schema(html: str) -> bool:
    return '"FAQPage"' in (html or "")


def insert_before_faq(body: str, fragment: str) -> str:
    """Insert fragment before the FAQ <details> block (or before the first
    trailing <script>, or append). Additive only — never removes content."""
    m = re.search(r"<details\b", body or "", re.I)
    if m:
        return body[:m.start()] + fragment + "\n" + body[m.start():]
    m = re.search(r'<script\b', body or "", re.I)
    if m:
        return body[:m.start()] + fragment + "\n" + body[m.start():]
    return (body or "") + "\n" + fragment


def validate_fragment(fragment: str, expect_tag: str) -> list[str]:
    """Safety checks for generated HTML before it touches a live article."""
    issues = []
    if not fragment or f"<{expect_tag}" not in fragment.lower():
        issues.append(f"missing <{expect_tag}>")
    if re.search(r"<h1\b", fragment or "", re.I):
        issues.append("contains <h1>")
    if re.search(r"<script\b", fragment or "", re.I):
        issues.append("contains <script>")
    for href in re.findall(r'href="([^"]+)"', fragment or ""):
        if not href.startswith(SITE):
            issues.append(f"external link: {href[:60]}")
    return issues


def gate_ok(state: dict, today: datetime.date, force: bool = False) -> tuple[bool, str]:
    if force:
        return True, "--force"
    last = state.get("last_run")
    if not last:
        return True, "no previous run"
    try:
        elapsed = (today - datetime.date.fromisoformat(last)).days
    except Exception:
        return True, "unparseable state"
    if elapsed >= INTERVAL_DAYS:
        return True, f"{elapsed}d since last run (>={INTERVAL_DAYS})"
    return False, f"only {elapsed}d since last run (<{INTERVAL_DAYS})"


def select_candidates(audit: dict, gsc_pages: dict, state: dict, ctr_state: dict,
                      today: datetime.date, cycle: int) -> list[dict]:
    """audit: {url: {words, has_table, handle}}; gsc_pages: {url: {impressions,...}}.
    Returns up to MAX_PER_CYCLE {url, handle, action, reason}."""
    def blocked(url: str) -> bool:
        entry = (state.get("articles") or {}).get(url)
        if entry:
            try:
                if (today - datetime.date.fromisoformat(entry["date"])).days < COOLDOWN_DAYS:
                    return True
            except Exception:
                pass
        ctr = ctr_state.get(url)
        if ctr and ctr.get("last_optimized"):
            try:
                if (today - datetime.date.fromisoformat(ctr["last_optimized"])).days < CTR_QUIET_DAYS:
                    return True
            except Exception:
                pass
        return False

    picks: list[dict] = []

    # Cycle 1: fixed seeds for the two known problems.
    if cycle == 1:
        for seed in SEEDS:
            if seed.get("handle"):
                match = next((u for u, a in audit.items()
                              if a.get("handle") == seed["handle"]), None)
            else:
                pref = seed["handle_prefix"]
                cands = [(gsc_pages.get(u, {}).get("impressions", 0), u)
                         for u, a in audit.items()
                         if a.get("handle", "").startswith(pref)]
                match = max(cands)[1] if cands else None
            if match and not blocked(match):
                action = seed["action"]
                if "table" in action and audit[match].get("has_table"):
                    # table already there — keep only the expansion part (if any)
                    action = "expand" if "expand" in action else ""
                if not action:
                    continue
                picks.append({"url": match, "handle": audit[match]["handle"],
                              "action": action, "reason": "cycle-1 seed"})
        return picks[:MAX_PER_CYCLE]

    # Later cycles: score by impressions × deficit.
    words_top = sorted((a["words"] for a in audit.values()), reverse=True)[:5]
    median_top = words_top[len(words_top) // 2] if words_top else 0
    scored: list[tuple[int, dict]] = []
    for url, a in audit.items():
        if blocked(url):
            continue
        impr = gsc_pages.get(url, {}).get("impressions", 0)
        if impr < 200:
            continue
        comparison_intent = bool(re.search(r"(-vs-|alternative|comparison|better-value)",
                                           a.get("handle", "")))
        if comparison_intent and not a.get("has_table"):
            scored.append((impr * 2, {"url": url, "handle": a["handle"], "action": "table",
                                      "reason": f"comparison page without table ({impr:,} impr)"}))
        elif median_top and a["words"] < 0.6 * median_top:
            scored.append((impr, {"url": url, "handle": a["handle"], "action": "expand",
                                  "reason": f"{a['words']} words vs top-median {median_top} ({impr:,} impr)"}))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [c for _, c in scored[:MAX_PER_CYCLE]]


# ── GSC measurement ──────────────────────────────────────────────────────────

def page_stats(token: str, url: str, start: datetime.date, end: datetime.date) -> dict:
    rows = _gsc_query(token, {
        "startDate": start.isoformat(), "endDate": end.isoformat(),
        "dimensions": ["page"],
        "dimensionFilterGroups": [{"filters": [
            {"dimension": "page", "operator": "equals", "expression": url}]}],
        "rowLimit": 1,
    })
    if not rows:
        return {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0}
    r = rows[0]
    return {"clicks": int(r.get("clicks", 0)), "impressions": int(r.get("impressions", 0)),
            "ctr": round(float(r.get("ctr", 0)) * 100, 2),
            "position": round(float(r.get("position", 0)), 1)}


def measure_due(state: dict, token: str, ctr_state: dict,
                today: datetime.date) -> list[str]:
    """Measure articles changed >=28d ago that have no result yet."""
    lines = []
    for url, entry in (state.get("articles") or {}).items():
        if entry.get("measured") or not entry.get("date"):
            continue
        try:
            changed = datetime.date.fromisoformat(entry["date"])
        except Exception:
            continue
        if (today - changed).days < INTERVAL_DAYS:
            continue
        before = page_stats(token, url, changed - datetime.timedelta(days=INTERVAL_DAYS),
                            changed - datetime.timedelta(days=1))
        after = page_stats(token, url, changed,
                           changed + datetime.timedelta(days=INTERVAL_DAYS - 1))
        overlap = False
        ctr_entry = ctr_state.get(url) or {}
        if ctr_entry.get("last_optimized"):
            try:
                d = abs((datetime.date.fromisoformat(ctr_entry["last_optimized"]) - changed).days)
                overlap = d <= INTERVAL_DAYS
            except Exception:
                pass
        outcome = ("improved" if after["clicks"] > before["clicks"]
                   or after["ctr"] > before["ctr"] else
                   "regressed" if after["clicks"] < before["clicks"] * 0.8 else "no_lift")
        entry["measured"] = {"date": today.isoformat(), "before": before, "after": after,
                             "outcome": outcome, "ctr_optimizer_overlap": overlap}
        icon = {"improved": "🟢", "no_lift": "⚪", "regressed": "🔴"}[outcome]
        note = " (⚠️ CTR-Optimizer im selben Fenster)" if overlap else ""
        lines.append(f"{icon} {entry.get('handle', url.rsplit('/', 1)[-1])[:40]} "
                     f"[{entry.get('action')}]: Klicks {before['clicks']}→{after['clicks']}, "
                     f"CTR {before['ctr']}%→{after['ctr']}%{note}")
    return lines


# ── content generation ───────────────────────────────────────────────────────

def _extract_html(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        raw = raw.lstrip("html").strip()
    return raw


def gen_table_fragment(client: Anthropic, title: str, body: str,
                       products: list[dict], price_str: str) -> str:
    plist = "\n".join(f"- {p['title']} — {p['url']}" for p in products[:6]) or "- (none)"
    r = client.messages.create(
        model=SONNET, max_tokens=2500,
        system=("You are the lead SEO editor for Velluto (velluto-shop.com), premium road "
                "cycling eyewear. Output ONLY an HTML fragment, no markdown fences, no commentary."),
        messages=[{"role": "user", "content":
            f"Article: \"{title}\"\n\nCreate ONE comparison <table> to insert into this "
            "article (searchers with comparison intent expect a side-by-side table).\n\n"
            "Rules:\n"
            f"1. Columns: criterion | Velluto StradaPro | Premium brands (Oakley etc.) | Budget options.\n"
            f"2. Velluto facts only from this list (real products):\n{plist}\n"
            f"   Velluto price: {price_str}. 25g ultralight, UV400, anti-fog, interchangeable "
            "lenses (VellutoPuro clear + VellutoVisione high-contrast), adjustable nose pads, "
            "30-day risk-free trial.\n"
            "3. Competitor columns: RANGES and general statements ONLY (e.g. '$150-$350', "
            "'proprietary lens system') — never specific competitor prices or invented specs.\n"
            "4. 6-9 comparison rows (price, weight, lens system, UV, anti-fog, fit, trial/returns…).\n"
            "5. Start with an <h2> introducing the table, then the <table>. Inline styles minimal "
            "(border-collapse, padding); no classes that don't exist, no <h1>, no <script>, "
            f"links (if any) only to {SITE}.\n"
            "6. Same language and tone as this excerpt:\n"
            f"{re.sub(r'<[^>]+>', ' ', body or '')[:800]}"}],
    )
    return _extract_html(r.content[0].text)


def load_paa_questions(handle: str, title: str, lang: str = "en") -> list[str]:
    """People-Also-Ask questions for this article, in `lang` (en/de/nl/…).
    Cluster keys stay English (matched against the handle/title); the questions
    come from data/paa_seed.json[lang][cluster]. Falls back to the English
    cluster questions when a market map has none yet (so nothing breaks before
    the native screenshots land). Merged with harvested SERP PAA for EN."""
    hay = f"{handle} {title}".lower()
    seed = _load(os.path.join(BASE, "data", "paa_seed.json"), {})
    # Back-compat: legacy flat {cluster: [...]} → treat as the "en" map.
    if seed and "en" not in seed and any(isinstance(v, list) for v in seed.values()):
        seed = {"en": {k: v for k, v in seed.items() if not k.startswith("_")}}
    market = seed.get(lang) or {}
    english = seed.get("en") or {}
    out: list[str] = []
    for cluster in english:  # cluster keys are English in every language map
        if cluster.lower() in hay:
            qs = market.get(cluster) or (english.get(cluster) if lang == "en" else [])
            out += [q for q in qs if isinstance(q, str)]
    if lang == "en":
        harvested = _load(os.path.join(BASE, "data", "processed", "paa_snapshots.json"), {})
        for item in harvested.get("extracted", []):
            kw = (item.get("keyword") or "").lower()
            if kw and any(tok in hay for tok in kw.split() if len(tok) > 4):
                out += [q.get("question", "") for q in item.get("questions", [])
                        if q.get("question")]
    return list(dict.fromkeys(out))[:8]


def gen_expansion_fragment(client: Anthropic, title: str, body: str,
                           queries: list[dict], paa: list[str] | None = None) -> str:
    q_lines = "\n".join(
        f"- \"{q['keys'][0]}\" ({int(q.get('impressions', 0))} impressions, "
        f"pos {q.get('position', 0):.1f})" for q in queries[:10]) or "- (no query data)"
    paa_block = ""
    if paa:
        paa_block = (
            "\nPEOPLE ALSO ASK (real questions Google shows for this topic — answer "
            "the relevant ones):\n" + "\n".join(f"- {q}" for q in paa) + "\n"
            "For each PAA question you cover: use the question (or a close variant) "
            "as an <h3> heading and open with a direct, self-contained 40-60 word "
            "answer (featured-snippet style) before going deeper.\n")
    r = client.messages.create(
        model=SONNET, max_tokens=6000,
        system=("You are the lead SEO editor for Velluto (velluto-shop.com), premium road "
                "cycling eyewear. Output ONLY an HTML fragment, no markdown fences, no commentary."),
        messages=[{"role": "user", "content":
            f"Article: \"{title}\"\n\nGoogle shows this article for these REAL queries — "
            f"but the article doesn't answer all of them in depth:\n{q_lines}\n{paa_block}\n"
            "Write 2-4 NEW <h2> sections (total 1,500-2,500 words) that answer the "
            "highest-impression queries the current article covers thinly.\n"
            "Rules:\n"
            "1. Expert advice from a faster, more experienced cycling friend — not a sales pitch.\n"
            "2. Velluto product claims: only 25g weight, UV400, anti-fog, interchangeable lenses, "
            "adjustable nose pads, 30-day trial. Velluto does NOT offer photochromic, polarized "
            "or prescription lenses (you may discuss those generically/for competitors).\n"
            "3. Competitor prices as ranges only. No invented facts, studies or statistics.\n"
            "4. Plain <h2>/<h3>/<p>/<ul> HTML. No <h1>, no <script>, no images, "
            f"links only to {SITE}.\n"
            "5. Do NOT repeat content that is clearly already in the article:\n"
            f"{re.sub(r'<[^>]+>', ' ', body or '')[:3000]}"}],
    )
    return _extract_html(r.content[0].text)


def adapt_fragment(client: Anthropic, fragment: str, locale: str) -> str:
    lang = LOCALE_LANG_NAMES.get(locale, locale)
    r = client.messages.create(
        model=HAIKU, max_tokens=6000,
        system=(f"Translate/adapt the HTML fragment to {lang} for cyclists in that market. "
                "Keep ALL HTML tags, attributes and structure IDENTICAL. Brand names "
                "(Velluto, StradaPro, VellutoPuro, VellutoVisione) and all URLs unchanged. "
                "No em-dash. Output ONLY the adapted HTML fragment."),
        messages=[{"role": "user", "content": fragment}],
    )
    return _extract_html(r.content[0].text)


# ── Shopify / state / reporting ──────────────────────────────────────────────

def fetch_articles() -> list[dict]:
    out, url = [], (f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json"
                    "?fields=id,title,handle,body_html&limit=250")
    while url:
        r = requests.get(url, headers=SHOPIFY_HEADERS, timeout=30)
        r.raise_for_status()
        out.extend(r.json().get("articles", []))
        url = next((p.split(";")[0].strip(" <>")
                    for p in r.headers.get("Link", "").split(",")
                    if 'rel="next"' in p), None)
    return out


def build_audit(articles: list[dict], blog_handle: str = "velluto-the-magazine") -> dict:
    audit = {}
    for a in articles:
        url = f"{SITE}/blogs/{blog_handle}/{a.get('handle', '')}"
        audit[url] = {"id": a["id"], "handle": a.get("handle", ""),
                      "title": a.get("title", ""),
                      "words": word_count(a.get("body_html", "")),
                      "has_table": has_table(a.get("body_html", "")),
                      "has_faq_schema": has_faq_schema(a.get("body_html", ""))}
    return audit


def _load(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def send_report(subject: str, text: str) -> None:
    """All bot communication is email-only (mailer no-ops without creds)."""
    try:
        import mailer
        mailer.send_email(subject, text)
    except Exception as e:
        print(f"   ⚠️  report email failed: {e}")


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    today = datetime.date.today()
    print(f"\n🛠  Velluto Content Retrofit — {today}")
    state = _load(STATE_PATH, {"last_run": None, "cycle": 0, "articles": {}})
    ok, why = gate_ok(state, today, FORCE)
    print(f"🗓  28-day gate: {'RUN' if ok else 'SKIP'} — {why}")
    if not ok:
        return

    ctr_state = _load(CTR_STATE_PATH, {})
    token = _gsc_token()

    # 1. MEASURE last cycle
    measure_lines: list[str] = []
    if token:
        measure_lines = measure_due(state, token, ctr_state, today)
        for line in measure_lines:
            print(f"   {line}")

    # 2. AUDIT current state (also consumed by seo_optimizer + daily_report)
    print("📚 Auditing articles…")
    articles = fetch_articles()
    audit = build_audit(articles)
    n_faq = sum(1 for a in audit.values() if a["has_faq_schema"])
    content_state = {
        "date": today.isoformat(),
        "articles": {u: {k: v for k, v in a.items() if k != "id"} for u, a in audit.items()},
        "faq_schema_coverage": round(n_faq / len(audit), 2) if audit else 0,
        "tables_on_comparison_pages": sum(
            1 for a in audit.values()
            if a["has_table"] and re.search(r"(-vs-|alternative|comparison)", a["handle"])),
    }
    _save(CONTENT_STATE_PATH, content_state)
    print(f"   {len(audit)} articles | FAQ-schema coverage {content_state['faq_schema_coverage']*100:.0f}%")

    # 3. SELECT
    gsc_pages = {}
    if token:
        rows = _gsc_query(token, {
            "startDate": (today - datetime.timedelta(days=28)).isoformat(),
            "endDate": today.isoformat(), "dimensions": ["page"], "rowLimit": 250})
        gsc_pages = {(r.get("keys") or [""])[0]: {"impressions": int(r.get("impressions", 0))}
                     for r in rows}
    cycle = int(state.get("cycle", 0)) + 1
    picks = select_candidates(audit, gsc_pages, state, ctr_state, today, cycle)
    if not picks:
        print("   ✓ No retrofit candidates this cycle")
        state["last_run"], state["cycle"] = today.isoformat(), cycle
        if not DRY_RUN:
            _save(STATE_PATH, state)
        return
    for p in picks:
        print(f"   → [{p['action']}] {p['handle']} ({p['reason']})")

    # 4. EXECUTE
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    from seo_bot import get_products
    from commercial_config import for_locale_short
    products = []
    try:
        products = get_products()
    except Exception:
        pass
    us = for_locale_short("en") or {}
    from commercial_config import from_price_str
    price_str = from_price_str("US")  # "from 69 EUR"

    done_lines: list[str] = []
    for pick in picks:
        art = audit[pick["url"]]
        full = next((a for a in articles if a["id"] == art["id"]), None)
        body = (full or {}).get("body_html", "")
        queries = []
        if token:
            try:
                queries = fetch_page_queries(token, pick["url"])
            except Exception:
                pass
        parts: list[str] = []
        try:
            if "table" in pick["action"]:
                frag = gen_table_fragment(client, art["title"], body, products, price_str)
                issues = validate_fragment(frag, "table")
                if issues:
                    print(f"   ❌ table fragment rejected for {pick['handle']}: {issues}")
                else:
                    parts.append(frag)
            if "expand" in pick["action"]:
                paa = load_paa_questions(pick["handle"], art["title"])
                if paa:
                    print(f"      +{len(paa)} PAA question(s) fed into the expansion")
                frag = gen_expansion_fragment(client, art["title"], body, queries, paa)
                issues = validate_fragment(frag, "h2")
                if issues:
                    print(f"   ❌ expansion fragment rejected for {pick['handle']}: {issues}")
                else:
                    parts.append(frag)
        except Exception as e:
            print(f"   ⚠️  generation failed for {pick['handle']}: {e}")
        if not parts:
            continue
        fragment = "\n".join(parts)
        expect = "table" if "table" in pick["action"] else "h2"

        added_words = word_count(fragment)
        print(f"   ✏️  {pick['handle']}: +{added_words} words ({pick['action']})")
        if DRY_RUN:
            print("   ── fragment preview ──")
            print(fragment[:600])
            continue

        new_body = insert_before_faq(body, fragment)
        if not put_body(art["id"], new_body):
            print(f"   ❌ body PUT failed for {pick['handle']}")
            continue
        digests = get_translatable_digests(art["id"])
        for locale in SHOP_LOCALES:
            tr = fetch_translations(art["id"], locale)
            if not tr.get("body_html"):
                continue
            try:
                adapted = adapt_fragment(client, fragment, locale)
                if validate_fragment(adapted, expect):
                    adapted = fragment  # fall back to EN fragment rather than skip
                tr_body = insert_before_faq(tr["body_html"], adapted)
                register_shopify_translation(art["id"], locale, tr.get("title", ""),
                                             tr_body, tr.get("meta_description", ""), digests)
            except Exception as e:
                print(f"   ⚠️  [{locale}] adaptation failed: {e}")

        before = {"words": art["words"]}
        if token:
            before.update(page_stats(token, pick["url"],
                                     today - datetime.timedelta(days=INTERVAL_DAYS),
                                     today - datetime.timedelta(days=1)))
        state.setdefault("articles", {})[pick["url"]] = {
            "cycle": cycle, "date": today.isoformat(), "action": pick["action"],
            "handle": pick["handle"], "added_words": added_words,
            "before": before, "measured": None,
        }
        done_lines.append(f"✏️ {pick['handle'][:40]} [{pick['action']}] +{added_words} Wörter")
        print("   ✅ updated (EN + translations)")

    # 5. REPORT + persist
    state["last_run"], state["cycle"] = today.isoformat(), cycle
    if not DRY_RUN:
        _save(STATE_PATH, state)
        msg = []
        if done_lines:
            msg.append("Umgesetzt:")
            msg += [f"• {l}" for l in done_lines]
        if measure_lines:
            msg.append("")
            msg.append("Messung Zyklus davor (28d vorher/nachher):")
            msg += [f"• {l}" for l in measure_lines]
        if msg:
            send_report(f"🛠 Content-Retrofit Zyklus {cycle} — {today}", "\n".join(msg))
    print(f"   Done — cycle {cycle}: {len(done_lines)} article(s) retrofitted")


if __name__ == "__main__":
    main()
