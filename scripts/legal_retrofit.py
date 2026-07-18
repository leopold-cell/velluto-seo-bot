"""
Legal-compliance retrofit for EXISTING live articles (EU/German advertising law).

Scans every published article's body for the highest-risk UWG/EU phrasings and,
with --apply, sets the clearly-risky ones to DRAFT (unpublished) so they go offline
for review/regeneration. Reversible (set published back to true after fixing, or let
the now-compliant bot refresh them). Dry-run by default — writes a report, changes
nothing. NOT legal advice.

Hybrid policy (operator-chosen):
  • fabricated tests/reviews OR disparaging/asymmetric competitor phrasing
      → DRAFT (concrete legal risk; needs a careful rewrite before it goes live)
  • false 'Dutch' origin, or other single soft hits
      → REVIEW only (listed in the report; not auto-drafted to avoid false
        positives like "popular among Dutch cyclists")

Usage:
  python3 scripts/legal_retrofit.py            # dry-run: report only
  python3 scripts/legal_retrofit.py --apply    # set risky articles to draft
"""
import datetime
import json
import os
import subprocess
import sys

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(dotenv_path=os.path.join(BASE, ".env"), override=True)

import seo_bot                                                            # noqa: E402
from briefs.quality_gate import _FAKE_TEST_RE, _DISPARAGE_RE, _ORIGIN_RE  # noqa: E402
from content_retrofit import fetch_articles                              # noqa: E402
from seo_bot import BLOG_ID, SHOPIFY_HEADERS, SHOPIFY_STORE              # noqa: E402


def _shopify_ok() -> bool:
    try:
        r = requests.get(
            f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json"
            "?limit=1&fields=id", headers=seo_bot.SHOPIFY_HEADERS, timeout=15)
        return r.status_code == 200
    except Exception:
        return False


def ensure_shopify() -> None:
    """Fail fast (before spending any generation cost): verify the Shopify token,
    and if it's missing/stale, mint a fresh one like run.sh does. Aborts with a
    clear message if that still fails — so we never generate articles we can't save."""
    if _shopify_ok():
        return
    print("   Shopify token stale/missing — minting a fresh one…")
    try:
        tok = subprocess.run([sys.executable, os.path.join(BASE, "mint_shopify_token.py")],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        if tok:
            seo_bot.SHOPIFY_HEADERS["X-Shopify-Access-Token"] = tok
            os.environ["SHOPIFY_TOKEN"] = tok
            if _shopify_ok():
                print(f"   ✓ minted fresh Shopify token ({tok[:8]}…)")
                return
    except Exception as e:
        print(f"   mint attempt failed: {e}")
    sys.exit("\n❌ Shopify auth failed and minting didn't help. Check SHOPIFY_CLIENT_ID / "
             "SHOPIFY_CLIENT_SECRET in .env, then re-run. (Nothing was generated.)")

APPLY   = "--apply" in sys.argv
URLS    = "--urls" in sys.argv       # print flagged URLs (for GSC Removals tool)
REWRITE = "--rewrite" in sys.argv    # surgical legal fix of flagged articles in place
STRIP   = "--strip-dashes" in sys.argv  # mechanical em-dash sweep across ALL articles
DRY_RUN = "--dry-run" in sys.argv    # with --rewrite/--strip-dashes: preview, don't write
REPORT_PATH = os.path.join(BASE, "output", "legal_retrofit_report.json")
SITE = "https://velluto-shop.com"
BLOG_HANDLE = "velluto-the-magazine"


def _url(handle: str) -> str:
    return f"{SITE}/blogs/{BLOG_HANDLE}/{handle}"


def _load_report() -> list:
    if not os.path.exists(REPORT_PATH):
        print("   ⚠️  no report found — run the scan first: python3 scripts/legal_retrofit.py")
        return []
    with open(REPORT_PATH, encoding="utf-8") as f:
        return json.load(f).get("findings", [])


_NOISE_RE = None
def _keyword_from(title: str, handle: str) -> str:
    """Derive a clean, compliant target keyword from a flagged article — strip the
    fabricated-test / ranking words so the rewrite doesn't reproduce the same angle
    (the compliance gate enforces the rest)."""
    import re
    base = re.sub(r"[-_]+", " ", handle or "")
    base = re.sub(r"\b(tested|ranked|compared|comparison|criteria|top|picks?|guide|"
                  r"honest|real|answer|velluto|stradapro|vs|de|te|the)\b", " ", base, flags=re.I)
    base = re.sub(r"\s+", " ", base).strip()
    return base or (title or "").strip()


def classify(title: str, body: str) -> dict:
    """Return {draft_reasons: [...], review_reasons: [...]}.

    draft_reasons  → high-confidence legal risk → set to draft on --apply.
    review_reasons → lower-confidence (origin, etc.) → report for human review.
    """
    blob = f"{title}\n{body}"
    draft, review = [], []
    if _FAKE_TEST_RE.search(blob):
        draft.append("fabricated test / first-hand-experience claim (§ 5/5a UWG + EU fake-review ban)")
    if _DISPARAGE_RE.search(blob):
        draft.append("disparaging / doubt-casting competitor phrasing (§ 6 Abs. 2 Nr. 5 UWG)")
    if _ORIGIN_RE.search(blob):
        review.append("possible false 'Dutch' origin near Velluto — verify it's not just context (§ 5 UWG)")
    return {"draft_reasons": draft, "review_reasons": review}


def set_published(article_id: int, published: bool) -> bool:
    try:
        r = requests.put(
            f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles/{article_id}.json",
            headers=SHOPIFY_HEADERS, timeout=20,
            json={"article": {"id": article_id, "published": published}})
        if r.status_code in (200, 201):
            return True
        print(f"   ❌ draft PUT failed {r.status_code}: {r.text[:150]}")
    except Exception as e:
        print(f"   ❌ draft PUT error: {e}")
    return False


def urls_mode() -> None:
    """Print the flagged article URLs for the GSC 'Removals' tool (copy-paste)."""
    findings = _load_report()
    draft = [f for f in findings if f.get("draft_reasons")]
    review = [f for f in findings if not f.get("draft_reasons") and f.get("review_reasons")]
    print(f"\n🔗 Flagged URLs from the last scan ({len(draft)} draft, {len(review)} review)\n")
    print("# 🔴 DRAFT — submit these to GSC → Removals (+ clear cached URL):")
    for f in draft:
        print(_url(f.get("handle", "")))
    if review:
        print("\n# 🟡 REVIEW — check manually before removing:")
        for f in review:
            print(_url(f.get("handle", "")))


import re as _re


def _wc_html(html: str) -> int:
    return len(_re.sub(r"<[^>]+>", " ", html or "").split())


def _links(html: str) -> int:
    return len(_re.findall(r"velluto-shop\.com", html or "", _re.I))


# Mechanical fixes (no LLM): safe, exact, can't break sentences.
_STATED_RE = _re.compile(r"\s*\(\s*(stated|claimed|self-?reported|allegedly|supposedly|unverified)\s*\)", _re.I)
_TITLE_TEST_RE = _re.compile(r"[\s:,\|&\-–—]*\b(tested|ranked|compared|comparison|hands[\s-]?on|reviewed?)\b", _re.I)


def _clean_title(title: str) -> str:
    t = _TITLE_TEST_RE.sub("", title or "")
    t = _re.sub(r"\s{2,}", " ", t).strip(" :,|&-–—")
    return t or title


def _mechanical(title: str, meta: str, body: str):
    from briefs.quality_gate import strip_em_dashes
    title = _clean_title(_STATED_RE.sub("", title or ""))
    meta  = _STATED_RE.sub("", meta or "")
    body  = _STATED_RE.sub("", body or "")
    return strip_em_dashes(title)[0], strip_em_dashes(meta)[0], strip_em_dashes(body)[0]


_EDIT_SYSTEM = (
    "You are a legal-compliance editor for a cycling-eyewear brand's OWN blog. Find the "
    "text that violates EU/German advertising law and return the minimal replacements to "
    "fix it. Violations:\n"
    "1. First-hand TEST/REVIEW claims — 'we tested', 'in our tests', 'hands-on', "
    "'road test', 'after N km/hours', star ratings, 'Testsieger', editorial-test framing. "
    "Reframe as an honest, spec-based buyer's guide.\n"
    "2. Disparaging/doubt-casting statements about named competitors — 'only claims', "
    "'merely', 'degrades', 'inferior', 'cheap', one-sided negatives, absolute 'does not "
    "offer X / doesn't publish its weights'. Use neutral, verifiable facts; describe "
    "Velluto's OWN strengths instead of a rival's weakness.\n"
    "2b. Any fact about a NAMED competitor that isn't 100% verifiable from that "
    "competitor's own public info: rewrite to remove it (general category or Velluto's "
    "own attributes).\n"
    "3. Never attribute photochromic/polarized/mirrored/prescription/over-glasses lenses "
    "to Velluto. Velluto offers only clear VellutoPuro and high-contrast VellutoVisione.\n"
    "4. Velluto is a GERMAN brand (Italian design) — never Dutch/Nederlands.\n"
    "5. The only Velluto price is 'from 69 EUR'; '89 EUR' is the free-shipping threshold, "
    "not the product price.\n"
    "Rules for replacements: same language as the article; similar length (do not shorten "
    "the article); keep any HTML tags/links inside the snippet; never introduce an "
    "em-dash '—'.\n"
    "Return ONLY a JSON array of edits: "
    '[{"find":"<text copied VERBATIM from the article, character-for-character>",'
    '"replace":"<compliant replacement>"}]. Include ONLY real violations. If nothing '
    "needs changing, return []."
)


def _llm_pairs(client, title: str, meta: str, body: str, lang_name: str, feedback: str):
    """Ask for targeted find/replace pairs (small output — no full-body regeneration)."""
    HAIKU = "claude-haiku-4-5-20251001"
    user = (f"LANGUAGE: {lang_name}\n\nAutomated checks flagged this article for:\n{feedback}\n\n"
            f"TITLE:\n{title}\n\nMETA:\n{meta}\n\nBODY_HTML:\n{body}")
    try:
        r = client.messages.create(model=HAIKU, max_tokens=3000, system=_EDIT_SYSTEM,
                                   messages=[{"role": "user", "content": user}])
        txt = r.content[0].text
    except Exception as e:
        print(f"      edit call failed: {e}")
        return []
    m = _re.search(r"\[.*\]", txt, _re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        return [p for p in data if isinstance(p, dict) and p.get("find")]
    except Exception:
        return []


def _apply_pairs(text: str, pairs: list) -> str:
    for p in pairs:
        f = (p.get("find") or "").strip()
        rep = p.get("replace") or ""
        if not f:
            continue
        if f in text:
            text = text.replace(f, rep)
        else:   # whitespace-tolerant fallback (model re-spaced the quote)
            toks = f.split()
            if toks:
                pat = r"\s+".join(_re.escape(t) for t in toks)
                text = _re.sub(pat, lambda _m: rep, text, count=1)
    return text


def _compliance_edit(client, title: str, body: str, meta: str, lang_name: str):
    """Fix ONLY the legal issues: mechanical first (cheap/exact), then targeted LLM
    find/replace pairs for the semantic ones. Returns (title, meta, body) or None if it
    couldn't produce a clean result. Targeted edits preserve content/links/length."""
    from briefs.quality_gate import check_compliance, strip_em_dashes
    title, meta, body = _mechanical(title, meta, body)
    base_wc = max(1, _wc_html(body))
    for _ in range(2):
        issues = check_compliance({"title": title, "meta_description": meta, "body_html": body})
        if not issues:
            break
        pairs = _llm_pairs(client, title, meta, body, lang_name, "\n".join(issues))
        if not pairs:
            break
        title = strip_em_dashes(_apply_pairs(title, pairs))[0]
        meta  = strip_em_dashes(_apply_pairs(meta, pairs))[0]
        body  = strip_em_dashes(_apply_pairs(body, pairs))[0]
    if _wc_html(body) < 0.7 * base_wc:                    # sanity: not gutted
        return None
    if check_compliance({"title": title, "meta_description": meta, "body_html": body}):
        return None                                       # still flagged — leave drafted
    return title, (meta or title)[:155], body


def rewrite_mode() -> None:
    """Surgically fix legally-risky wording in existing articles IN PLACE (same URL):
    a single targeted edit pass per article + per translation — keep the rest of the
    content untouched. Far lighter than a full regeneration and preserves the SEO.
    Re-scans ALL live articles (also picks up ones you drafted manually)."""
    from anthropic import Anthropic
    from briefs.quality_gate import check_compliance
    from seo_bot import replace_article, readapt_all_translations, ALLOWED_TAGS
    from commercial_config import load_commercial_config

    ensure_shopify()
    commercial = load_commercial_config()
    articles = fetch_articles()
    flagged = [a for a in articles
               if check_compliance({"title": a.get("title", ""), "body_html": a.get("body_html", "")})]
    print(f"\n🩹 Compliance fix — {len(flagged)}/{len(articles)} articles need editing "
          f"({'DRY-RUN' if DRY_RUN else 'LIVE in-place edit'})")

    if DRY_RUN:
        for a in flagged:
            iss = check_compliance({"title": a.get("title", ""), "body_html": a.get("body_html", "")})
            print(f"   • {a.get('handle','')[:55]}")
            for i in iss:
                print(f"       {i}")
        print("\n   DRY-RUN — nothing edited. Re-run without --dry-run to fix + re-publish in place.")
        return

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    done = 0
    for a in flagged:
        print(f"\n── Fixing {a.get('handle','')[:55]} ──")
        fixed = _compliance_edit(client, a.get("title", ""), a.get("body_html", ""), "", "English")
        if not fixed:
            print("   ⚠️  no clean edit produced — left unchanged (keep it drafted)")
            continue
        nt, nm, nb = fixed
        try:
            replace_article(a["id"], nt, nb, nm, ",".join(ALLOWED_TAGS))
        except Exception as e:
            print(f"   ❌ replace failed: {e}")
            continue
        # Re-adapt ALL languages freshly from the corrected EN via Translate & Adapt
        # (creates missing ones too) — not a patch of the old translations.
        try:
            n = readapt_all_translations(a["id"], {"title": nt, "body_html": nb,
                                                   "meta_description": nm}, commercial)
            print(f"   🌍 {n} language(s) re-adapted via T&A")
        except Exception as e:
            print(f"   ⚠️  translation re-adapt issue: {e}")
        done += 1
        print("   ✅ fixed in place (EN surgical + all languages re-translated)")

    print(f"\n   ✓ {done}/{len(flagged)} articles fixed & re-published in place (same URLs). "
          f"Request re-indexing in GSC so the clean version replaces the cached one.")


def strip_dashes_mode() -> None:
    """Cheap mechanical sweep: remove the AI em-dash '—' (and spaced en-dash) from
    EVERY article title/body + translations. No LLM, preserves publish state."""
    from briefs.quality_gate import strip_em_dashes
    from seo_bot import (get_translatable_digests, register_shopify_translation,
                         SHOP_LOCALES)
    from backfill_seo_cleanup import fetch_translations
    ensure_shopify()
    articles = fetch_articles()
    hit = 0
    for a in articles:
        t0, b0 = a.get("title", ""), a.get("body_html", "")
        t1, tc = strip_em_dashes(t0)
        b1, bc = strip_em_dashes(b0)
        if not (tc or bc):
            continue
        hit += 1
        print(f"   ✂️  {a.get('handle','')[:55]}")
        if DRY_RUN:
            continue
        try:
            r = requests.put(
                f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles/{a['id']}.json",
                headers=seo_bot.SHOPIFY_HEADERS, timeout=20,
                json={"article": {"id": a["id"], "title": t1, "body_html": b1}})  # no 'published' → state kept
            if r.status_code not in (200, 201):
                print(f"      ❌ PUT {r.status_code}: {r.text[:120]}"); continue
            digests = get_translatable_digests(a["id"])
            for loc in SHOP_LOCALES:
                tr = fetch_translations(a["id"], loc)
                if not tr.get("body_html"):
                    continue
                tb, tcc = strip_em_dashes(tr["body_html"])
                tt, ttc = strip_em_dashes(tr.get("title", ""))
                if tcc or ttc:
                    register_shopify_translation(a["id"], loc, tt, tb,
                                                 strip_em_dashes(tr.get("meta_description", ""))[0], digests)
        except Exception as e:
            print(f"      ⚠️  {e}")
    print(f"\n   {'would strip' if DRY_RUN else 'stripped'} em-dashes in {hit}/{len(articles)} articles"
          + ("  (dry-run — nothing written)" if DRY_RUN else ""))


def main() -> None:
    if URLS:
        urls_mode(); return
    if STRIP:
        strip_dashes_mode(); return
    if REWRITE:
        rewrite_mode(); return
    print(f"\n⚖️  Legal-compliance retrofit — {datetime.date.today()} "
          f"({'APPLY' if APPLY else 'DRY-RUN'})")
    articles = fetch_articles()
    print(f"   scanned {len(articles)} articles\n")

    to_draft, to_review, report = [], [], []
    for a in articles:
        res = classify(a.get("title", ""), a.get("body_html", ""))
        if not (res["draft_reasons"] or res["review_reasons"]):
            continue
        rec = {"id": a["id"], "handle": a.get("handle", ""), "title": a.get("title", ""),
               **res}
        report.append(rec)
        if res["draft_reasons"]:
            to_draft.append(a)
            print(f"🔴 DRAFT  {a.get('handle', '')[:55]}")
            for r in res["draft_reasons"]:
                print(f"          • {r}")
        elif res["review_reasons"]:
            to_review.append(a)
            print(f"🟡 REVIEW {a.get('handle', '')[:55]}")
            for r in res["review_reasons"]:
                print(f"          • {r}")

    print(f"\n   {len(to_draft)} to draft · {len(to_review)} to review · "
          f"{len(articles) - len(report)} clean")

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump({"date": datetime.date.today().isoformat(), "applied": APPLY,
                   "findings": report}, f, ensure_ascii=False, indent=2)
    print(f"   report → {os.path.relpath(REPORT_PATH, BASE)}")

    if not APPLY:
        print("\n   DRY-RUN — nothing changed. Re-run with --apply to set the 🔴 "
              "articles to draft (reversible).")
        return

    ensure_shopify()
    print("\n   Applying: setting 🔴 articles to draft…")
    done = 0
    for a in to_draft:
        if set_published(a["id"], False):
            done += 1
            print(f"   ⏸  drafted: {a.get('handle', '')[:55]}")
    print(f"\n   ✓ {done}/{len(to_draft)} articles set to draft. Review/rewrite them, "
          f"then re-publish (or let the now-compliant bot refresh them). 🟡 review "
          f"items were left live — check them manually.")


if __name__ == "__main__":
    main()
