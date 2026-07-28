#!/usr/bin/env python3
"""
Scrub internal links that point at drafted (unpublished) blog articles.

Background (GSC alert 2026-07-28, „Nicht gefunden (404) … in einer Sitemap"):
legal_retrofit.py takes an article offline (draft) when no compliant rewrite is
possible. Its URL then 404s in all 12 locales — but OTHER published articles may
still link to it (verified live: 2 published articles linked to the drafted
best-oakley-alternatives-… article). Dead internal links keep Googlebot
re-crawling the 404s and leak internal link equity.

What it does:
  1. Lists ALL blog articles (any status) → splits published vs drafted.
  2. Scans every published article's EN body + every locale translation for
     <a> tags whose href points at a drafted article's handle.
  3. Unwraps those links (anchor text stays, <a> tag goes) — or, with
     --retarget <url>, rewrites the href to that live URL instead.
     Self-link guard: if the retarget URL is the scanned article itself,
     the link is unwrapped, never self-linked.
  4. Verifies the live EN blog sitemap: every listed URL must return 200
     (no auth needed — runs even without Shopify credentials via --sitemap-only).

NOTE: if a drafted article will be fixed and re-published shortly (same URL),
prefer `legal_retrofit.py --republish-clean` and skip scrubbing — unwrapped
links do NOT come back on republish.

Idempotent. Dry-run by default; pass --apply to write.

Usage:
  python3 scripts/scrub_drafted_links.py                 # dry-run (report only)
  python3 scripts/scrub_drafted_links.py --apply         # unwrap dead links
  python3 scripts/scrub_drafted_links.py --apply \
      --retarget https://velluto-shop.com/blogs/velluto-the-magazine/best-cycling-glasses-value-2026-oakley-vs-velluto-vs-decathlon
  python3 scripts/scrub_drafted_links.py --sitemap-only  # just the 200-check
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

APPLY        = "--apply" in sys.argv
SITEMAP_ONLY = "--sitemap-only" in sys.argv
RETARGET     = ""
if "--retarget" in sys.argv:
    i = sys.argv.index("--retarget")
    RETARGET = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
    if not RETARGET.startswith("https://"):
        print("Error: --retarget needs an absolute https:// URL of a LIVE page.")
        sys.exit(1)

BLOG_SITEMAP = "https://velluto-shop.com/sitemap_blogs_1.xml"


# ── Sitemap health check (no auth) ────────────────────────────────────────────

def _get_status(url: str) -> int:
    """GET with 429-aware retries. Shopify's bot shield throttles bursts of
    storefront requests from one IP — a 429 here is OUR rate, not a site error,
    so back off (honouring Retry-After) and try again before reporting."""
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=15, allow_redirects=False)
            code = r.status_code
        except Exception:
            code = 0
        if code != 429:
            return code
        wait = 2 ** (attempt + 1)  # 2, 4, 8s
        try:
            wait = max(wait, int(r.headers.get("Retry-After", 0)))
        except (TypeError, ValueError):
            pass
        time.sleep(wait)
    return 429


def check_sitemap() -> int:
    """Fetch the EN blog sitemap and GET every URL. Returns count of non-200s."""
    print(f"\n🩺 Sitemap health — {BLOG_SITEMAP}")
    try:
        xml = requests.get(BLOG_SITEMAP, timeout=20).text
    except Exception as e:
        print(f"   ✗ could not fetch sitemap: {e}")
        return -1
    urls = re.findall(r"<loc>([^<]+)</loc>", xml)
    bad = 0
    for u in urls:
        code = _get_status(u)
        if code != 200:
            bad += 1
            print(f"   ✗ {code} {u}")
        time.sleep(1.0)  # stay under Shopify's storefront burst limit
    print(f"   {len(urls)} URLs checked · {bad} not 200"
          + ("  ✅" if bad == 0 else "  — fix these (GSC will report them)"))
    return bad


# ── Link scrubbing (needs Shopify credentials) ───────────────────────────────

def _link_rx(handle: str) -> re.Pattern:
    # <a … href="…/blogs/<blog>/<handle>[?#"]…">anchor</a>  (locale prefixes too)
    return re.compile(
        r'<a\b[^>]*href="[^"]*/blogs/[^"/]+/' + re.escape(handle) + r'(?:[?#][^"]*)?"[^>]*>(.*?)</a>',
        re.S | re.I,
    )


def _scrub(html: str, drafted_handles: list[str], own_handle: str) -> tuple[str, int]:
    """Unwrap (or retarget) links to drafted handles. Returns (new_html, n_hits)."""
    retarget = RETARGET if (RETARGET and own_handle and own_handle not in RETARGET) else ""

    def repl(m: re.Match) -> str:
        if not retarget:
            return m.group(1)  # unwrap: keep anchor text
        tag = m.group(0)
        start = tag.index('href="') + len('href="')
        end = tag.index('"', start)
        return tag[:start] + retarget + tag[end:]

    out, n = html or "", 0
    for h in drafted_handles:
        rx = _link_rx(h)
        hits = len(rx.findall(out))
        if hits:
            n += hits
            out = rx.sub(repl, out)
    return out, n


def main() -> None:
    mode = "APPLY" if APPLY else "DRY-RUN"
    print(f"=== scrub_drafted_links.py [{mode}]"
          + (f" retarget→{RETARGET}" if RETARGET else " (unwrap)") + " ===")

    if not SITEMAP_ONLY:
        from seo_bot import (  # noqa: E402 — heavy import, only when needed
            SHOPIFY_STORE, SHOPIFY_HEADERS, BLOG_ID, SHOP_LOCALES,
            get_translatable_digests, register_shopify_translation, graphql_with_vars,
        )

        def _list_articles() -> list[dict]:
            out, url = [], (
                f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles.json"
                "?fields=id,title,handle,body_html,published_at&limit=250&published_status=any"
            )
            while url:
                r = requests.get(url, headers=SHOPIFY_HEADERS, timeout=30)
                r.raise_for_status()
                out.extend(r.json().get("articles", []))
                url = next((p.split(";")[0].strip(" <>")
                            for p in r.headers.get("Link", "").split(",")
                            if 'rel="next"' in p), None)
            return out

        def _read_translation(aid: int, locale: str) -> dict[str, str]:
            q = """
            query($id: ID!, $locale: String!) {
              translatableResource(resourceId: $id) {
                translations(locale: $locale) { key value }
              }
            }"""
            data = graphql_with_vars(q, {"id": f"gid://shopify/Article/{aid}", "locale": locale})
            items = ((data.get("translatableResource") or {}).get("translations") or [])
            return {it["key"]: it["value"] for it in items}

        articles = _list_articles()
        drafted = [a for a in articles if not a.get("published_at")]
        published = [a for a in articles if a.get("published_at")]
        print(f"\n{len(articles)} articles · {len(published)} published · {len(drafted)} drafted")
        for d in drafted:
            print(f"   ⏸  drafted: {d.get('handle','')}")

        if not drafted:
            print("   nothing drafted — no links to scrub.")
        else:
            handles = [d["handle"] for d in drafted if d.get("handle")]
            fixed_en = fixed_tx = 0
            for a in published:
                aid, title, own = a["id"], a.get("title", ""), a.get("handle", "")
                new_body, n = _scrub(a.get("body_html", ""), handles, own)
                if n:
                    print(f"[EN] '{title[:50]}' (#{aid}) — {n} dead link(s)")
                    if APPLY:
                        r = requests.put(
                            f"https://{SHOPIFY_STORE}/admin/api/2024-01/blogs/{BLOG_ID}/articles/{aid}.json",
                            headers=SHOPIFY_HEADERS, timeout=20,
                            json={"article": {"id": aid, "body_html": new_body}})
                        print(f"     {'✅ updated' if r.status_code == 200 else '❌ failed ' + str(r.status_code)}")
                    fixed_en += 1

                digests = None
                for loc in SHOP_LOCALES:
                    tx = _read_translation(aid, loc)
                    new_tx, n = _scrub(tx.get("body_html", ""), handles, own)
                    if not n:
                        continue
                    print(f"[{loc}] '{title[:40]}' (#{aid}) — {n} dead link(s)")
                    if APPLY:
                        if digests is None:
                            digests = get_translatable_digests(aid)
                        ok = register_shopify_translation(
                            aid, loc,
                            title=tx.get("title", ""),
                            body_html=new_tx,
                            meta_desc=tx.get("summary_html", ""),
                            digests=digests,
                        )
                        print(f"     {'✅ re-registered' if ok else '❌ failed'}")
                    fixed_tx += 1

            print(f"\n=== Summary ===")
            print(f"EN bodies with dead links:          {fixed_en}")
            print(f"Locale translations with dead links: {fixed_tx}")
            if not APPLY and (fixed_en or fixed_tx):
                print("\nDRY-RUN — no changes written. Re-run with --apply to scrub.")

    bad = check_sitemap()
    sys.exit(1 if bad > 0 else 0)


if __name__ == "__main__":
    main()
