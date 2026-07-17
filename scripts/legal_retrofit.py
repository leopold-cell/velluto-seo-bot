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
import sys

import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(dotenv_path=os.path.join(BASE, ".env"), override=True)

from briefs.quality_gate import _FAKE_TEST_RE, _DISPARAGE_RE, _ORIGIN_RE  # noqa: E402
from content_retrofit import fetch_articles                              # noqa: E402
from seo_bot import BLOG_ID, SHOPIFY_HEADERS, SHOPIFY_STORE              # noqa: E402

APPLY   = "--apply" in sys.argv
URLS    = "--urls" in sys.argv       # print flagged URLs (for GSC Removals tool)
REWRITE = "--rewrite" in sys.argv    # regenerate drafted articles compliantly in place
DRY_RUN = "--dry-run" in sys.argv    # with --rewrite: preview targets, don't generate
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


def rewrite_mode() -> None:
    """Regenerate each drafted article through the compliant pipeline and re-publish
    it IN PLACE (same URL). Reuses seo_bot.publish_de_primary(replace_id=…)."""
    findings = _load_report()
    drafted = [f for f in findings if f.get("draft_reasons")]
    print(f"\n♻️  Compliance rewrite — {len(drafted)} drafted article(s) "
          f"({'DRY-RUN preview' if DRY_RUN else 'LIVE regenerate + republish'})")
    if not drafted:
        return
    if DRY_RUN:
        for f in drafted:
            print(f"   • {f.get('handle','')[:55]}  →  keyword: '{_keyword_from(f.get('title',''), f.get('handle',''))}'")
        print("\n   DRY-RUN — nothing generated. Re-run without --dry-run to rewrite + republish.")
        return
    from seo_bot import publish_de_primary, get_products
    from commercial_config import load_commercial_config
    products = get_products()
    commercial = load_commercial_config()
    done = 0
    for f in drafted:
        kw_str = _keyword_from(f.get("title", ""), f.get("handle", ""))
        kw = {"keyword": kw_str, "keyword_en": kw_str, "phase": "legal-rewrite",
              "angle": "buying_guide", "art_num": None}
        print(f"\n── Rewriting {f.get('handle','')[:55]} (kw: '{kw_str}') ──")
        try:
            publish_de_primary(kw, products, commercial=commercial, replace_id=f["id"])
            done += 1
        except Exception as e:
            print(f"   ⚠️  rewrite failed (stays drafted): {e}")
    print(f"\n   ✓ {done}/{len(drafted)} articles rewritten compliantly & re-published "
          f"in place. Request re-indexing for these URLs in GSC so the clean version "
          f"replaces the cached one.")


def main() -> None:
    if URLS:
        urls_mode(); return
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
