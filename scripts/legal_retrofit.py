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


_EDIT_SYSTEM = (
    "You are a legal-compliance editor for a cycling-eyewear brand's OWN blog. You "
    "receive one article and must edit it MINIMALLY to remove EU/German advertising-law "
    "risks — change as LITTLE as possible, keep all HTML tags/structure, headings, "
    "links, images, tables, the language, and roughly the same length and message.\n"
    "Fix ONLY these:\n"
    "1. Remove any claim or implication of a first-hand TEST/REVIEW/measurement — "
    "'we tested', 'in our tests', 'hands-on', 'tested', 'ranked', 'road test', "
    "'after N km/hours', star ratings, 'Testsieger', editorial-test framing. Reframe "
    "as an honest, spec-based buyer's guide.\n"
    "2. Remove disparaging or doubt-casting statements about named competitors — "
    "'(stated)', 'only claims', 'merely', 'degrades', 'inferior', 'cheap', one-sided "
    "negatives, and absolute 'does not offer X / doesn't publish its weights'. Keep "
    "only neutral, verifiable, current facts; describe Velluto's OWN strengths instead "
    "of a rival's weakness.\n"
    "2b. Remove ANY fact about a named competitor that cannot be verified with 100% "
    "certainty from that competitor's own public information. If a comparison point "
    "needs unverifiable competitor data, do NOT name the competitor there — write "
    "about the general category or Velluto's own attributes instead.\n"
    "2c. Never use the em-dash '—' or a spaced en-dash ' – ' anywhere — use commas or "
    "periods (normal hyphens in words are fine).\n"
    "3. Never attribute photochromic / polarized / mirrored / prescription / "
    "over-glasses lenses to Velluto (competitors may have them). Velluto offers only "
    "clear VellutoPuro and high-contrast VellutoVisione.\n"
    "4. Velluto is a GERMAN brand (Italian design) — never Dutch/Nederlands.\n"
    "5. The only Velluto price is 'from 69 EUR'; '89 EUR' is the free-shipping "
    "threshold, not the product price.\n"
    "SEO PRESERVATION (critical — must not hurt rankings):\n"
    "- Keep the article's MAIN TOPIC KEYWORD in the title; only strip the misleading "
    "test/ranking words (e.g. 'Tested', 'Ranked', 'Compared'). Do not change the topic.\n"
    "- Do NOT shorten the article. When you remove a non-compliant sentence, REPLACE "
    "it with an equally substantial compliant sentence on the same subject (Velluto's "
    "own strengths or a neutral, verifiable category fact) — keep the word count and depth.\n"
    "- Preserve EVERY internal link to velluto-shop.com, every <h2>/<h3> heading, every "
    "table and the FAQ block, exactly.\n"
    "Output EXACTLY this format, nothing else:\n"
    "===TITLE===\n<corrected title>\n===META===\n<corrected meta description, <=155 chars>"
    "\n===BODY===\n<corrected full HTML body>"
)


def _parse_edit(txt: str):
    if "===BODY===" not in txt:
        return None
    head, body = txt.split("===BODY===", 1)
    body = body.strip()
    if body.startswith("```"):
        body = body.split("```", 2)[1] if body.count("```") >= 2 else body.lstrip("`")
        body = _re.sub(r"^html\s*", "", body).strip()
    t = _re.search(r"===TITLE===\s*(.*?)\s*===META===", head, _re.S)
    m = _re.search(r"===META===\s*(.*)", head, _re.S)
    return ((t.group(1).strip() if t else ""), (m.group(1).strip() if m else ""), body)


def _compliance_edit(client, title: str, body: str, meta: str, lang_name: str):
    """One targeted LLM edit pass that fixes ONLY the legal issues. Returns
    (title, meta, body) or None if it couldn't produce a clean, intact edit."""
    from briefs.quality_gate import check_compliance, strip_em_dashes
    HAIKU = "claude-haiku-4-5-20251001"

    def run(feedback=""):
        user = (f"LANGUAGE: {lang_name}\n\nTITLE:\n{title}\n\nMETA:\n{meta}\n\n"
                f"BODY_HTML:\n{body}"
                + (f"\n\nThese issues are STILL present — fix them:\n{feedback}" if feedback else ""))
        try:
            r = client.messages.create(model=HAIKU, max_tokens=8000, system=_EDIT_SYSTEM,
                                       messages=[{"role": "user", "content": user}])
            return _parse_edit(r.content[0].text)
        except Exception as e:
            print(f"      edit call failed: {e}")
            return None

    parsed = run()
    for _ in range(2):
        if not parsed or not parsed[2]:
            return None
        nt, nm, nb = parsed
        nt = strip_em_dashes(nt)[0]; nm = strip_em_dashes(nm)[0]; nb = strip_em_dashes(nb)[0]
        ok_len   = _wc_html(nb) >= 0.8 * max(1, _wc_html(body))   # don't shrink >20%
        ok_links = _links(nb)   >= _links(body)                   # keep internal links
        issues   = check_compliance({"title": nt, "meta_description": nm, "body_html": nb})
        if ok_len and ok_links and not issues:
            return nt, (nm or nt)[:155], nb
        fb = list(issues)
        if not ok_len:
            fb.append("Do NOT shorten — keep the full length; replace removed sentences "
                      "with compliant ones of similar length.")
        if not ok_links:
            fb.append("Keep ALL internal velluto-shop.com links present in the original.")
        parsed = run("\n".join(fb))
    return None


def rewrite_mode() -> None:
    """Surgically fix legally-risky wording in existing articles IN PLACE (same URL):
    a single targeted edit pass per article + per translation — keep the rest of the
    content untouched. Far lighter than a full regeneration and preserves the SEO.
    Re-scans ALL live articles (also picks up ones you drafted manually)."""
    from anthropic import Anthropic
    from briefs.quality_gate import check_compliance
    from seo_bot import (replace_article, get_translatable_digests,        # noqa
                         register_shopify_translation, SHOP_LOCALES, LOCALE_LANG_NAMES,
                         ALLOWED_TAGS)
    from backfill_seo_cleanup import fetch_translations

    ensure_shopify()
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
        try:
            digests = get_translatable_digests(a["id"])
            for loc in SHOP_LOCALES:
                tr = fetch_translations(a["id"], loc)
                if not tr.get("body_html"):
                    continue
                tfix = _compliance_edit(client, tr.get("title", "") or nt, tr["body_html"],
                                        tr.get("meta_description", ""), LOCALE_LANG_NAMES.get(loc, loc))
                if tfix:
                    register_shopify_translation(a["id"], loc, tfix[0], tfix[2], tfix[1], digests)
        except Exception as e:
            print(f"   ⚠️  translation fix issue: {e}")
        done += 1
        print("   ✅ fixed in place (EN + translations)")

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
