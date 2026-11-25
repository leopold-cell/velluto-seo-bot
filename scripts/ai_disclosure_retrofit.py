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

from briefs.ai_disclosure import (add_notice, ai_image_stems, is_public_interest_topic,  # noqa: E402
                                  label_ai_images)

APPLY = "--apply" in sys.argv
MAX_PER_RUN = 25
STATE = os.path.join(ROOT, "data", "ai_disclosure_state.json")


def _state(arts: list, stems: set) -> set:
    """Finished article ids. v1 (a plain list, bottom label only) counts as finished only
    for articles that do not need the label at the TOP or an image label."""
    try:
        raw = json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return set()
    if isinstance(raw, dict) and raw.get("v") == 2:
        return set(raw.get("done", []))
    redo = {a["id"] for a in arts
            if is_public_interest_topic(a.get("handle", ""))
            or any(st in (a.get("body_html") or "") for st in stems)}
    return {i for i in raw if i not in redo}


def _fix(body: str, lang: str, top: bool, stems: set) -> str:
    """The body as it should be: image labels and the notice in the right place."""
    return add_notice(label_ai_images(body, lang, stems), lang, top=top)


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

    stems = ai_image_stems()
    done = _state(arts, stems)
    todo = [a for a in arts if a["id"] not in done]
    print(f"=== ai_disclosure_retrofit [{'APPLY' if APPLY else 'DRY-RUN'}] — "
          f"{len(todo)} von {len(arts)} Artikeln offen ===")
    n = 0
    for a in todo[:MAX_PER_RUN]:
        aid, body = a["id"], a.get("body_html") or ""
        ok_all = True
        top = is_public_interest_topic(a.get("handle", ""))
        new_en = _fix(body, "en", top, stems)
        if new_en.strip() != body.strip():
            print(f"  [en] {a['handle']}" + (" (Hinweis oben)" if top else ""))
            if APPLY:
                resp = requests.put(f"{api}/blogs/{BLOG_ID}/articles/{aid}.json",
                                    headers=SHOPIFY_HEADERS, timeout=30,
                                    json={"article": {"id": aid, "body_html": new_en}})
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
            new_tx = _fix(tbody, loc, top, stems) if tbody else ""
            if not tbody or new_tx.strip() == tbody.strip():
                continue
            print(f"  [{loc}] {a['handle']}")
            if APPLY:
                digests = digests or get_translatable_digests(aid)
                ok_all &= bool(register_shopify_translation(
                    aid, loc, title=tx.get("title", ""), body_html=new_tx,
                    meta_desc=tx.get("meta_description", tx.get("summary_html", "")),
                    digests=digests))
        if APPLY and ok_all:
            done.add(aid)
            n += 1
    if APPLY:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump({"v": 2, "done": sorted(done)}, open(STATE, "w", encoding="utf-8"))
        left = len([a for a in arts if a["id"] not in done])
        print(f"\n{n} Artikel gekennzeichnet, {left} offen." if left
              else "\nalle Artikel gekennzeichnet.")
    else:
        print("\nDRY-RUN — mit --apply schreiben.")


if __name__ == "__main__":
    main()
