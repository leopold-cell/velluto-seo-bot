"""
Post discovery for the engagement bot.

Instagram killed the hashtag grids: /explore/tags/{tag}/ now returns 0 posts to
logged-in automation, which is exactly why the old bot stopped finding anything.
So instead of hashtags we find active cyclists two more durable ways:

  1. ENGAGERS of seed accounts (primary): open a cycling account's recent posts
     and read the COMMENTERS. Comment lists still render in the DOM (like lists
     are hidden), and people who comment on cycling content are real, active
     cyclists worth engaging. We then engage with each commenter's own latest
     post — same downstream flow as before (author of the target post = the
     person we engage).
  2. LOCATION tags (secondary): /explore/locations/{id}/ grids for cycling
     hotspots are far less restricted than hashtag grids.

discover() returns a de-duplicated list of TARGET post URLs. bot.py then
processes each exactly as it always did (visit → author → like/comment/follow).

Pure helpers (regex/dedup) are unit-testable; the page-driven ones are not.
"""
from __future__ import annotations

import random
import re
import time

_PROFILE_RE = re.compile(r"^/([a-zA-Z0-9._]{2,30})/$")
_POST_RE    = re.compile(r"/(?:p|reel)/([^/?#]+)")           # posts AND reels
# DOM-independent fallbacks over raw page HTML/JSON (IG churns the DOM often):
_HTML_CODE_RE = re.compile(r"/(p|reel)/([A-Za-z0-9_-]{5,})")
_JSON_CODE_RE = re.compile(r'"(?:short)?code"\s*:\s*"([A-Za-z0-9_-]{6,15})"')


# ── pure helpers ─────────────────────────────────────────────────────────────

def post_id(url: str) -> str:
    m = _POST_RE.search(url or "")
    return m.group(1) if m else ""


def _abs(href: str) -> str:
    if href.startswith("/"):
        return "https://www.instagram.com" + href
    return href


def dedupe_posts(urls: list[str], seen_ids: set[str] | None = None) -> list[str]:
    """De-dup by post id, preserving order, skipping ids already in seen_ids."""
    out, ids = [], (seen_ids or set())
    for u in urls:
        pid = post_id(u)
        if not pid or pid in ids:
            continue
        ids.add(pid)
        out.append(u)
    return out


def clean_username(raw: str) -> str:
    """Normalize a profile handle from an href or text; '' if not a handle."""
    raw = (raw or "").strip()
    if raw.startswith("@"):
        raw = raw[1:]
    m = _PROFILE_RE.match(raw if raw.startswith("/") else f"/{raw}/")
    return m.group(1) if m else ""


# ── page-driven collectors (best-effort, never raise) ────────────────────────

def _sleep(lo=1.2, hi=2.6):
    time.sleep(random.uniform(lo, hi))


def _dismiss(page) -> None:
    """Close cookie/consent/interstitial overlays that hide the grid. Soft."""
    for sel in ("button:has-text('Not Now')", "button:has-text('Jetzt nicht')",
                "button:has-text('Allow all cookies')", "button:has-text('Alle Cookies erlauben')",
                "button:has-text('Decline optional cookies')", "button:has-text('Dismiss')",
                "button:has-text('Schließen')", "[aria-label='Close']", "[aria-label='Schließen']"):
        try:
            b = page.query_selector(sel)
            if b:
                b.click(timeout=2000)
                time.sleep(random.uniform(0.6, 1.2))
        except Exception:
            pass
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def _page_signals(page) -> dict:
    """Cheap check of where we actually landed — detects login/challenge/block."""
    try:
        url = (page.url or "").lower()
    except Exception:
        url = ""
    blocked = any(x in url for x in
                  ("/accounts/login", "/challenge", "/suspended", "/accounts/suspended"))
    return {"url": url, "blocked": blocked}


def extract_post_links(page, log=print) -> list[str]:
    """Collect post/reel URLs from an already-loaded page.

    DOM anchors first (`/p/` and `/reel/`); if the DOM yields nothing, fall back
    to regex over the raw HTML/JSON payload — resilient to IG's DOM churn (the
    shortcodes are usually still embedded in the page's inline JSON even when the
    anchor tiles aren't in the initial DOM).
    """
    urls: list[str] = []
    try:
        for el in page.query_selector_all("a[href*='/p/'], a[href*='/reel/']"):
            href = el.get_attribute("href") or ""
            if "/p/" in href or "/reel/" in href:
                urls.append(_abs(href))
    except Exception as e:
        log(f"    discovery: DOM extract failed: {e}")
    if not urls:                                   # DOM empty → try the payload
        try:
            html = page.content()
            for kind, code in _HTML_CODE_RE.findall(html):
                urls.append(f"https://www.instagram.com/{kind}/{code}/")
            for code in _JSON_CODE_RE.findall(html):
                urls.append(f"https://www.instagram.com/p/{code}/")
            if urls:
                log(f"    discovery: DOM empty — regex fallback found {len(dedupe_posts(urls))} codes")
        except Exception as e:
            log(f"    discovery: regex fallback failed: {e}")
    return dedupe_posts(urls)


def collect_post_links(page, url: str, scrolls: int = 6, log=print) -> list[str]:
    """Open a grid page (profile or location) and collect its post URLs."""
    try:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        _sleep(4, 6)
        _dismiss(page)
        try:
            page.wait_for_selector("a[href*='/p/'], a[href*='/reel/']", timeout=8000)
        except Exception:
            pass                                   # regex fallback may still hit
        for _ in range(scrolls):
            try:
                page.evaluate("window.scrollBy(0, 900)")
            except Exception:
                break
            time.sleep(random.uniform(1.2, 2.2))
        return extract_post_links(page, log=log)
    except Exception as e:
        log(f"    discovery: grid load failed for {url}: {e}")
        return []


def commenters_on_post(page, post_url: str, max_users: int = 12, log=print) -> list[str]:
    """Open a post and return the usernames that COMMENTED (real active users)."""
    try:
        page.goto(post_url, timeout=30000, wait_until="domcontentloaded")
        _sleep(3, 5)
        _dismiss(page)
        users, seen = [], set()
        # Comment author links live inside the comment list; grab profile hrefs.
        for el in page.query_selector_all("ul a[href], div[role='presentation'] a[href]"):
            href = el.get_attribute("href") or ""
            u = clean_username(href)
            if u and u not in seen:
                seen.add(u)
                users.append(u)
            if len(users) >= max_users:
                break
        return users
    except Exception as e:
        log(f"    discovery: commenters failed for {post_url}: {e}")
        return []


def latest_post_of_user(page, username: str, log=print) -> str:
    """Return the URL of a user's most recent post/reel (first grid tile), or ''."""
    try:
        page.goto(f"https://www.instagram.com/{username}/", timeout=25000,
                  wait_until="domcontentloaded")
        _sleep(3, 5)
        _dismiss(page)
        links = extract_post_links(page, log=log)
        if links:
            return links[0]
    except Exception as e:
        log(f"    discovery: latest post failed for @{username}: {e}")
    return ""


# ── main entry ───────────────────────────────────────────────────────────────

def discover(page, seed_accounts: list[str], location_ids: list[str],
             want: int, skip_users: set[str], seen_ids: set[str], log=print) -> list[str]:
    """Return up to ~`want` target post URLs to engage with.

    Primary: seed account → recent posts → commenters → their latest post.
    Secondary: location grids. De-duped by post id and against seen_ids;
    posts authored by skip_users can't be filtered here (author is only known
    once bot.py opens the post) — that stays in bot.py's engaged/SKIP check.
    """
    targets: list[str] = []
    ids = set(seen_ids or set())

    # ── Strategy 1: engagers of seed accounts ──
    seeds = list(seed_accounts or [])
    random.shuffle(seeds)
    empty_streak = 0
    block_hit = False
    for acct in seeds:
        if len(targets) >= want:
            break
        acct = clean_username(acct) or acct
        posts = collect_post_links(page, f"https://www.instagram.com/{acct}/",
                                   scrolls=3, log=log)[:4]
        if not posts:
            sig = _page_signals(page)
            if sig["blocked"]:
                block_hit = True
                log(f"  discovery: seed @{acct} — BLOCKED/redirect → {sig['url'][:60]}")
            else:
                log(f"  discovery: seed @{acct} — no posts (private/blocked?)")
            empty_streak += 1
            # Protect the account: don't hammer all seeds when we're clearly being
            # blocked, or when the first few seeds are all dry (nothing to gain).
            if block_hit or (empty_streak >= 3 and not targets):
                log(f"  discovery: early-exit after {empty_streak} empty seed(s)"
                    + (" + block signal (cookie stale / action-block?)" if block_hit else "")
                    + " — stopping to protect the account")
                break
            continue
        empty_streak = 0
        log(f"  discovery: seed @{acct} — {len(posts)} posts, reading commenters")
        for post in posts[:2]:
            if len(targets) >= want:
                break
            for user in commenters_on_post(page, post, max_users=10, log=log):
                if user in skip_users:
                    continue
                latest = latest_post_of_user(page, user, log=log)
                pid = post_id(latest)
                if latest and pid and pid not in ids:
                    ids.add(pid)
                    targets.append(latest)
                if len(targets) >= want:
                    break
            _sleep(3, 6)

    # ── Strategy 2: location grids (bonus) ──
    # Skip if we already hit a login/challenge redirect — locations won't fare
    # better and every extra request digs the block deeper.
    for loc in ([] if block_hit else (location_ids or [])):
        if len(targets) >= want:
            break
        url = f"https://www.instagram.com/explore/locations/{loc}/"
        for p in collect_post_links(page, url, scrolls=5, log=log):
            pid = post_id(p)
            if pid and pid not in ids:
                ids.add(pid)
                targets.append(p)
            if len(targets) >= want:
                break

    log(f"  discovery: {len(targets)} candidate posts collected")
    return targets
