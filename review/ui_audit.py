"""
Mobile + desktop UI audit via Playwright screenshots + Claude vision.

For each selected article we render mobile (390x844) and desktop (1440x900),
screenshot, and ask Claude (vision) whether the layout "looks good" and to list
concrete issues (overflow, left-misalignment, broken images, cramped tables,
clipped text). Degrades gracefully if Playwright/Chromium is unavailable.

Scope (cost control): all posts published in the last `interval_days`, plus a
rotating sample of older posts, plus any flagged by cheap HTML heuristics —
since all posts share the magazine template, this catches template regressions.
"""
from __future__ import annotations

import base64
import datetime as _dt
import re

from review._common import SONNET, complete, parse_json_block, have_anthropic, review_config

VIEWPORTS = {"mobile": (390, 844), "desktop": (1440, 900)}


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def _heuristic_flag(article: dict) -> bool:
    body = article.get("body_html", "") or ""
    img_count = len(re.findall(r"<img\b", body, re.I))
    has_big_table = bool(re.search(r"<table", body, re.I)) and body.count("<tr") >= 6
    return img_count >= 6 or has_big_table


def select_targets(articles: list[dict]) -> list[dict]:
    cfg = review_config()
    interval = cfg["interval_days"]
    sample_size = cfg["ui_sample_size"]
    cutoff = _dt.date.today() - _dt.timedelta(days=interval)

    def _pub_date(a):
        try:
            return _dt.datetime.fromisoformat(
                (a.get("published_at") or "").replace("Z", "+00:00")).date()
        except Exception:
            return _dt.date.min

    recent = [a for a in articles if _pub_date(a) >= cutoff]
    flagged = [a for a in articles if _heuristic_flag(a)]
    # rotating sample of older posts, deterministic by day-of-year
    older = [a for a in articles if a not in recent]
    if older:
        offset = _dt.date.today().timetuple().tm_yday % max(1, len(older))
        rotated = older[offset:] + older[:offset]
        sample = rotated[:sample_size]
    else:
        sample = []

    seen, targets = set(), []
    for a in recent + flagged + sample:
        if a["handle"] not in seen:
            seen.add(a["handle"])
            targets.append(a)
    return targets


def _screenshot(url: str) -> dict[str, str]:
    """Return {viewport: base64_png}. Empty dict on failure."""
    shots: dict[str, str] = {}
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            for name, (w, h) in VIEWPORTS.items():
                page = browser.new_page(viewport={"width": w, "height": h},
                                        device_scale_factor=1)
                try:
                    page.goto(url, wait_until="networkidle", timeout=30000)
                    page.wait_for_timeout(800)
                    png = page.screenshot(full_page=True)
                    shots[name] = base64.b64encode(png).decode("ascii")
                except Exception as e:
                    print(f"   ⚠️  ui: screenshot {name} failed for {url}: {e}")
                finally:
                    page.close()
            browser.close()
    except Exception as e:
        print(f"   ⚠️  ui: playwright unavailable: {e}")
    return shots


_UI_SYSTEM = (
    "You are a meticulous web-UI reviewer. You receive a MOBILE and a DESKTOP "
    "full-page screenshot of the same blog article. Judge visual quality. "
    "Return ONLY JSON: {\"verdict\":\"good|minor|broken\","
    "\"mobile_issues\":[\"...\"],\"desktop_issues\":[\"...\"]}. "
    "Flag: content not centered / left-hugging on desktop, horizontal overflow, "
    "overlapping or clipped text, broken/oversized/uneven images, cramped tables, "
    "tiny tap targets. If it looks clean, say verdict 'good' with empty arrays."
)


def review_article_ui(article: dict) -> dict:
    shots = _screenshot(article["url"])
    if not shots:
        return {"handle": article["handle"], "verdict": "skipped",
                "reason": "no screenshots (playwright/chromium missing or render failed)"}
    if not have_anthropic():
        return {"handle": article["handle"], "verdict": "skipped",
                "reason": "no ANTHROPIC_API_KEY for vision", "captured": list(shots)}
    images = [{"media_type": "image/png", "data": d} for d in
              (shots.get("mobile"), shots.get("desktop")) if d]
    user = (f"Article: {article.get('title','')}\nURL: {article['url']}\n"
            f"Image 1 = MOBILE (390px), Image 2 = DESKTOP (1440px).")
    out = complete(_UI_SYSTEM, user, model=SONNET, max_tokens=600, images=images)
    parsed = parse_json_block(out)
    if not isinstance(parsed, dict):
        parsed = {"verdict": "unknown", "raw": out[:400]}
    parsed["handle"] = article["handle"]
    parsed["url"] = article["url"]
    return parsed


def audit(articles: list[dict]) -> dict:
    if not playwright_available():
        return {"skipped": True, "reason": "playwright not installed", "results": []}
    targets = select_targets(articles)
    results = [review_article_ui(a) for a in targets]
    broken = [r for r in results if r.get("verdict") == "broken"]
    minor = [r for r in results if r.get("verdict") == "minor"]
    return {
        "skipped": False,
        "targets": len(targets),
        "broken": len(broken),
        "minor": len(minor),
        "results": results,
    }
