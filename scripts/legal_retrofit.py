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

APPLY = "--apply" in sys.argv
REPORT_PATH = os.path.join(BASE, "output", "legal_retrofit_report.json")


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


def main() -> None:
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
