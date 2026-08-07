#!/usr/bin/env python3
"""
Standing legal watchdog — checks what is PUBLISHED, in every language.

WHY A WATCHDOG AND NOT ANOTHER GATE
An audit of this repo found 22 surfaces that put text in front of the public and
only 4 of them behind check_compliance(). The gate runs once, on the English
source; translations, URL slugs, JSON-LD, FAQ answers, image alt text, the SEO
metafields written by meta_optimizer and every social re-syndication are all
derivatives created afterwards. Gating 22 write paths one at a time is what
produced the whack-a-mole: each fix was a reaction to something noticed by hand.

Checking the rendered page instead catches all of them at once, including the
ones no gate can reach (theme copy, anything a Shopify app injects). Prevention
where it is cheap, detection everywhere.

WHAT IT CHECKS, per URL and per locale:
  · visible page text          · <title> (the SEO title_tag metafield)
  · meta description           · JSON-LD blocks (Article headline, FAQPage Q&A)
  · every image alt attribute  · the URL slug itself

Weekly, self-gating, fails soft, writes data/legal_watchdog.json and surfaces in
the daily mail. Read-only — it never edits anything, it only reports.

Usage:
  python3 scripts/legal_watchdog.py             # gated weekly
  python3 scripts/legal_watchdog.py --force     # run now
  python3 scripts/legal_watchdog.py --force --locales de,nl
"""
import datetime as dt
import html as html_mod
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from briefs.quality_gate import check_compliance  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY = os.path.join(ROOT, "data", "legal_watchdog.json")
SITE = "https://velluto-shop.com"
SITEMAP = f"{SITE}/sitemap_blogs_1.xml"

LOCALES = ["", "de", "nl", "fr", "it", "es", "sv", "da", "nb", "pl", "pt-pt"]
if "--locales" in sys.argv:
    i = sys.argv.index("--locales")
    if i + 1 < len(sys.argv):
        LOCALES = [x.strip() for x in sys.argv[i + 1].split(",")]

FORCE = "--force" in sys.argv
GATE_DAYS = 7
PAUSE = 0.4          # Shopify throttles bursts; a 429 would look like a clean page


def _get(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Velluto-legal-watchdog/1.0"})
        return urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "ignore")
    except Exception:
        return ""


def _visible_text(html: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))


def _surfaces(html: str, url: str) -> dict[str, str]:
    """Every place text reaches a reader, as {surface_name: text}."""
    out: dict[str, str] = {}
    out["body"] = _visible_text(html)

    m = re.search(r"<title>([^<]*)</title>", html, re.I)
    if m:
        out["title-tag"] = html_mod.unescape(m.group(1))

    m = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', html, re.I)
    if m:
        out["meta-description"] = html_mod.unescape(m.group(1))

    # JSON-LD carries the Article headline and the FAQ Q&A — both are appended to
    # the body AFTER the publish-time gate, so nothing else ever sees them.
    ld = " ".join(re.findall(r'<script[^>]+ld\+json[^>]*>(.*?)</script>', html, re.S | re.I))
    if ld.strip():
        out["json-ld"] = html_mod.unescape(re.sub(r"\s+", " ", ld))

    alts = re.findall(r'<img[^>]+alt="([^"]*)"', html, re.I)
    alts = [html_mod.unescape(a) for a in alts if a.strip()]
    if alts:
        out["image-alt"] = " · ".join(alts)

    # The slug is advertising too — it is what Google prints under the title.
    out["url-slug"] = url.rsplit("/", 1)[-1].replace("-", " ")
    return out


def scan(locales: list[str]) -> list[dict]:
    handles = [u.rsplit("/", 1)[-1]
               for u in re.findall(r"<loc>([^<]+)</loc>", _get(SITEMAP))]
    handles = [h for h in handles if h and h != "velluto-the-magazine"]
    print(f"🔍 legal watchdog — {len(handles)} articles × {len(locales)} locale(s)")

    findings, checked = [], 0
    for loc in locales:
        prefix = f"{SITE}/{loc}" if loc else SITE
        for h in handles:
            url = f"{prefix}/blogs/velluto-the-magazine/{h}"
            page = _get(url)
            time.sleep(PAUSE)
            if not page:
                continue
            checked += 1
            for surface, text in _surfaces(page, url).items():
                for issue in check_compliance({"title": "", "body_html": text}):
                    findings.append({"locale": loc or "en", "handle": h,
                                     "surface": surface, "issue": issue[:160],
                                     "url": url})
        print(f"   [{loc or 'en'}] done")
    print(f"   {checked} pages checked · {len(findings)} finding(s)")
    return findings


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def main() -> None:
    hist = _load(HISTORY, [])
    if not FORCE and hist:
        try:
            last = dt.date.fromisoformat(hist[-1]["date"])
            if (dt.date.today() - last).days < GATE_DAYS:
                print("   legal watchdog: scanned <7 days ago — nothing to do")
                return
        except Exception:
            pass

    findings = scan(LOCALES)

    # Group so one bad sentence in an article does not read as 11 problems.
    by_article: dict[str, dict] = {}
    for f in findings:
        key = f["handle"]
        e = by_article.setdefault(key, {"handle": key, "locales": set(),
                                        "surfaces": set(), "issue": f["issue"],
                                        "url": f["url"]})
        e["locales"].add(f["locale"])
        e["surfaces"].add(f["surface"])

    entry = {"date": dt.date.today().isoformat(),
             "locales": len(LOCALES),
             "findings": len(findings),
             "articles": len(by_article),
             "detail": [{"handle": v["handle"],
                         "locales": sorted(v["locales"]),
                         "surfaces": sorted(v["surfaces"]),
                         "issue": v["issue"], "url": v["url"]}
                        for v in by_article.values()][:40]}
    hist.append(entry)
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(hist[-52:], f, ensure_ascii=False, indent=1)

    if not by_article:
        print("   ✅ nothing flagged across all locales.")
        return
    print(f"\n⚠️  {len(by_article)} article(s) flagged:\n")
    for v in entry["detail"]:
        print(f"  • {v['handle'][:56]}")
        print(f"      {'/'.join(v['locales'])} · {', '.join(v['surfaces'])}")
        print(f"      {v['issue']}")


if __name__ == "__main__":
    main()
