#!/usr/bin/env python3
"""
Put the AI-content label (briefs/ai_disclosure.py) at the bottom of every published
blog article that does not have it yet: the English body via REST and each locale
translation via translationsRegister. New articles get the label at generation time;
this covers the ones published before 2026-11-25.

Idempotent: data/ai_disclosure_state.json remembers finished articles, and an article
whose bodies already carry the label is skipped. At most MAX_PER_RUN articles per run
(about 22 API calls each) so the daily pipeline never stalls; run it daily until the
log says "alle Artikel gekennzeichnet". Dry-run by default; run.sh passes --apply.

Usage:
  python3 scripts/ai_disclosure_retrofit.py            # dry-run
  python3 scripts/ai_disclosure_retrofit.py --apply
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from briefs.ai_disclosure import add_notice, has_notice, notice_html  # noqa: E402

APPLY = "--apply" in sys.argv
MAX_PER_RUN = 25
STATE = os.path.join(ROOT, "data", "ai_disclosure_state.json")


def _state() -> set:
    try:
        return set(json.load(open(STATE, encoding="utf-8")))
    except Exception:
        return set()


def main() -> None:
    import requests
    from seo_bot import (BLOG_ID, SHOP_LOCALES, SHOPIFY_HEADERS, SHOPIFY_STORE,
                         get_translatable_digests, graphql_with_vars,
                         register_shopify_translation)

    api = f"https://{SHOPIFY_STORE}/admin/api/2024-01"
    url = (f"{api}/blogs/{BLOG_ID}/articles.json"
           "?fields=id,handle,body_html&limit=250&published_status=published")
    arts = []
    while url:
        r = requests.get(url, headers=SHOPIFY_HEADERS, timeout=30)
        r.raise_for_status()
        arts.extend(r.json().get("articles", []))
        url = next((p.split(";")[0].strip(" <>")
                    for p in r.headers.get("Link", "").split(",")
                    if 'rel="next"' in p), None)

    done = _state()
    todo = [a for a in arts if a["id"] not in done]
    print(f"=== ai_disclosure_retrofit [{'APPLY' if APPLY else 'DRY-RUN'}] — "
          f"{len(todo)} von {len(arts)} Artikeln offen ===")
    n = 0
    for a in todo[:MAX_PER_RUN]:
        aid, body = a["id"], a.get("body_html") or ""
        ok_all = True
        if not has_notice(body):
            print(f"  [en] {a['handle']}")
            if APPLY:
                resp = requests.put(f"{api}/blogs/{BLOG_ID}/articles/{aid}.json",
                                    headers=SHOPIFY_HEADERS, timeout=30,
                                    json={"article": {"id": aid, "body_html": add_notice(body, "en")}})
                ok_all = resp.status_code == 200
        gid = f"gid://shopify/Article/{aid}"
        digests = None
        for loc in SHOP_LOCALES:
            res = graphql_with_vars(
                "query($id: ID!, $l: String!){ translatableResource(resourceId: $id)"
                "{ translations(locale: $l){ key value } } }", {"id": gid, "l": loc})
            tx = {t["key"]: t["value"] for t in
                  ((res.get("translatableResource") or {}).get("translations") or [])}
            tbody = tx.get("body_html", "")
            if not tbody or notice_html(loc) in tbody:
                continue
            print(f"  [{loc}] {a['handle']}")
            if APPLY:
                digests = digests or get_translatable_digests(aid)
                ok_all &= bool(register_shopify_translation(
                    aid, loc, title=tx.get("title", ""), body_html=add_notice(tbody, loc),
                    meta_desc=tx.get("meta_description", tx.get("summary_html", "")),
                    digests=digests))
        if APPLY and ok_all:
            done.add(aid)
            n += 1
    if APPLY:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump(sorted(done), open(STATE, "w", encoding="utf-8"))
        left = len([a for a in arts if a["id"] not in done])
        print(f"\n{n} Artikel gekennzeichnet, {left} offen." if left
              else "\nalle Artikel gekennzeichnet.")
    else:
        print("\nDRY-RUN — mit --apply schreiben.")


if __name__ == "__main__":
    main()
