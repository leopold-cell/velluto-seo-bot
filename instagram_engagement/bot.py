"""
Velluto Instagram engagement bot (Playwright, cookie session).

Discovery was rebuilt (see discovery.py): Instagram killed /explore/tags/ grids,
so we now find active cyclists via seed-account engagers + location grids. All
downstream engagement (like / AI comment / follow / reply / unfollow / daily
summary email) is unchanged.

ToS note: automated engagement is against Instagram's ToS and carries an
account-block/ban risk. Keep LIMITS modest, keep the human-paced sleeps, and
watch the daily summary for action-blocks. Use --dry-run to verify discovery
finds posts WITHOUT taking any action.

Usage:
  python3 bot.py --session 1|2|3          # live
  python3 bot.py --session 1 --dry-run    # discover + log only, no actions
"""
import argparse, base64, json, os, random, re, smtplib, subprocess, sys, time
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
import anthropic
try:
    from langdetect import detect as _langdetect, DetectorFactory as _DF; _DF.seed = 42
    _LANGDETECT_OK = True
except ImportError:
    _LANGDETECT_OK = False

import discovery
from config import SEED_ACCOUNTS, LOCATION_IDS

# ── Paths & Config ─────────────────────────────────────────────────────────────
BASE_DIR          = Path(__file__).parent
COOKIES_FILE      = BASE_DIR / "session.json"
ENGAGED_FILE      = BASE_DIR / "engaged.json"
REPLIED_FILE      = BASE_DIR / "replied.json"
SUMMARY_FILE      = BASE_DIR / "summaries.log"
OPTIMIZE_FILE     = BASE_DIR / "optimization.log"
LOG_DIR           = BASE_DIR / "logs"
FOLLOWS_FILE      = BASE_DIR / "follows.json"

API_KEY           = os.environ.get("ANTHROPIC_API_KEY", "")
EMAIL_FROM        = os.environ.get("EMAIL_FROM", "")
EMAIL_APP_PASS    = os.environ.get("EMAIL_APP_PASS", "")
EMAIL_TO          = os.environ.get("EMAIL_TO", "leopold@velluto-brand.com")

# Per-session limits. Start conservative when re-warming an account.
LIMITS            = {"likes": 12, "comments": 8, "follows": 6, "unfollows": 6, "replies": 5}
ENGAGE_TTL_DAYS   = 30
MAX_TOTAL         = 26      # hard cap on total actions per session
SESSION_MAX_SECS  = 900     # 15-minute hard cap per session
COMMENT_COOLDOWN  = 60      # seconds between two comments
SKIP              = {"velluto.cc", "velluto_cc", "unknown", ""}

DRY_RUN           = False   # set by --dry-run: discover + log, take NO actions


# ── Helpers ────────────────────────────────────────────────────────────────────
def log(msg):
    LOG_DIR.mkdir(exist_ok=True)
    ts   = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    lf = LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    with open(lf, "a") as f:
        f.write(line + "\n")

def load_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default

def save_json(path, data):
    path.write_text(json.dumps(data, indent=2))

def sleep(lo=1.5, hi=3.5):
    time.sleep(random.uniform(lo, hi))

def is_dach(text):
    t = text.lower()
    de_words = ["ich","mein","und","mit","von","auf","das","die","der","ist","bin",
                "hab","heute","wieder","noch","auch","nach","beim","wir","sie","hat",
                "war","kann","will","mal","schon","sehr","eine","einen"]
    locs = ["wien","berlin","munchen","zurich","bern","hamburg","koln","frankfurt",
            "innsbruck","graz","salzburg","deutschland","osterreich","schweiz",
            "sudtirol","tirol","austria","germany","switzerland"]
    for w in de_words:
        if re.search(rf"\b{w}\b", t): return True
    for loc in locs:
        if loc in t: return True
    return False

def get_username(page):
    for el in page.query_selector_all("a[href]")[:80]:
        href = el.get_attribute("href") or ""
        text = el.inner_text().strip()
        if re.match(r"^/[a-zA-Z0-9._]{3,30}/$", href) and text and "/" not in text:
            return text
    return "unknown"

def get_caption(page):
    """Best-effort caption extraction using body text + timestamp anchor."""
    import re as _re
    try:
        body = page.evaluate("() => document.body.innerText")
        lines = [l.strip() for l in body.splitlines()]
        ts_pat = _re.compile(r'^(\d+[wdhm]|Just now|gestern|heute|[Jj]etzt)$')
        for i, line in enumerate(lines):
            if ts_pat.match(line):
                cap_lines = []
                for j in range(i+1, min(i+12, len(lines))):
                    l = lines[j]
                    if not l:
                        continue
                    if l in ("See translation", "Übersetzung anzeigen", "Like",
                             "Comment", "Share", "Save", "Follow", "Following",
                             "More posts from", "Meta", "About"):
                        break
                    cap_lines.append(l)
                cap = " ".join(cap_lines).strip()
                if len(cap) >= 15:
                    return cap[:400]
    except Exception:
        pass
    try:
        texts = page.evaluate("""() => {
            const spans = Array.from(document.querySelectorAll('span'));
            return spans
                .map(s => s.innerText ? s.innerText.trim() : '')
                .filter(t => t.length > 20 && t.length < 500
                    && !t.startsWith('@') && !t.startsWith('#')
                    && !t.includes('Following') && !t.includes('Follow'));
        }""")
        if texts:
            return max(texts, key=len)[:400]
    except Exception:
        pass
    return ""

def dismiss_overlays(page):
    for sel in ["button:has-text('Not Now')", "button:has-text('Jetzt nicht')",
                "button:has-text('Dismiss')", "button:has-text('Schließen')",
                "[role='dialog'] button:last-child"]:
        try:
            btn = page.query_selector(sel)
            if btn:
                btn.click(timeout=2000)
                sleep(0.8, 1.5)
                break
        except Exception:
            pass
    try:
        page.keyboard.press("Escape")
        sleep(0.3, 0.6)
    except Exception:
        pass

def ai_comment(client, page, caption: str, german: bool):
    """Generate a contextual comment via Claude using a post screenshot + caption."""
    lang = "German" if german else "English"
    try:
        article = page.query_selector("article")
        box = article.bounding_box() if article else None
        clip = ({"x": box["x"], "y": box["y"],
                 "width": min(box["width"], 640), "height": min(box["height"], 640)}
                if box else {"x": 0, "y": 0, "width": 640, "height": 640})
        img_b64 = base64.b64encode(page.screenshot(clip=clip)).decode()
    except Exception as e:
        log(f"    screenshot error: {e}")
        img_b64 = ""
    content = []
    if img_b64:
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": img_b64}})
    text = f"Post caption: {caption[:300]}" if caption else "No caption — describe what you see."
    content.append({"type": "text", "text": text})
    try:
        r = client.messages.create(
            model="claude-sonnet-4-5", max_tokens=60,
            system=(
                f"You are a real cyclist commenting on a friend's Instagram post. "
                f"Language: {lang}. Maximum 15 words. "
                f"STYLE — vary format naturally like real users: "
                f"(A) short punchy question: 'where was this?', 'how are the legs after that?' "
                f"(B) casual reaction + question: 'that climb looks brutal 😅 how long did it take?' "
                f"(C) short enthusiastic reaction: 'those views though 🔥🙌'. "
                f"Choose what fits, don't always follow one pattern. 1-2 fitting emojis, not always. "
                f"Lowercase/casual is fine. RULES: (1) always positive, never negative/sarcastic. "
                f"(2) specific to image+caption, never generic. (3) no brand names, no hashtags, "
                f"never start with an emoji. (4) output the comment text ONLY."
            ),
            messages=[{"role": "user", "content": content}])
        return r.content[0].text.strip().strip(chr(34)).strip(chr(39))
    except Exception as e:
        log(f"    ai_comment error: {e}")
        return None

def validate_comment(text):
    """Safety gate — length, single '?', positivity, no spam/generic/links."""
    if not text:
        return False
    if len(text) < 8 or len(text) > 150:
        return False
    if text.count("?") > 1:
        return False
    if text.lstrip().startswith(("http", "@", "#")):
        return False
    if not re.search(r"[a-zA-ZäöüÄÖÜßéèàçñ]", text):   # must contain letters, not emoji-only
        return False
    low = text.lower()
    banned = [
        "great post", "nice post", "cool post", "love this post", "amazing post",
        "check out", "dm me", "follow me", "link in bio", "promo", "giveaway",
        "hate", "ugly", "trash", "sucks", "worst", "stupid", "boring", "awful",
    ]
    if any(b in low for b in banned):
        return False
    return True

def post_comment(page, text):
    """Post a comment. Returns True on success."""
    try:
        dismiss_overlays(page)
        ta = page.query_selector("textarea")
        if not ta:
            placeholder = page.query_selector(
                "[aria-label*='omment'], [aria-label*='ommentar'], "
                "[placeholder*='omment'], [placeholder*='ommentar']")
            if placeholder:
                placeholder.click(force=True, timeout=5000)
                sleep(1.2, 2.0)
                ta = page.query_selector("textarea")
        if not ta:
            return False
        ta.click(force=True, timeout=5000)
        sleep(1.2, 2.0)
        page.keyboard.type(text, delay=40)
        sleep(1.5, 2.5)
        btn = page.query_selector("form button[type='submit']")
        if btn and btn.is_enabled():
            btn.click(timeout=5000)
        else:
            page.keyboard.press("Enter")
        sleep(12, 20)
        return True
    except Exception as e:
        log(f"    comment error: {e}")
        return False

def click_follow_btn(page):
    try:
        for btn in page.query_selector_all("button, div[role='button']"):
            try:
                if btn.inner_text().strip() in ("Follow", "Folgen"):
                    btn.click(timeout=5000)
                    sleep(10, 20)
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False

def quality_check(username):
    return username not in SKIP

def already_commented(page):
    try:
        for el in page.query_selector_all("article ul li, div[role='presentation'] li"):
            if "velluto" in el.inner_text().lower():
                return True
    except Exception:
        pass
    return False

def ai_reply(client, reply_text, german):
    lang = "German" if german else "English"
    r = client.messages.create(
        model="claude-sonnet-4-5", max_tokens=60,
        system=(f"You reply as @velluto.cc cycling eyewear. Language: {lang}. "
                f"Max 12 words. Warm, funny, positive. End with a question if natural. "
                f"No brand mentions, no hashtags. Return ONLY the reply text."),
        messages=[{"role": "user", "content": f"Reply to: {reply_text[:200]}"}])
    return r.content[0].text.strip().strip('"')


# ── Phase 1: Reply to incoming comments ───────────────────────────────────────
def check_replies(page, client, replied, api_calls):
    log("\n── Checking replies ──")
    count = 0
    try:
        page.goto("https://www.instagram.com/notifications/", timeout=30000)
        sleep(4, 6)
        seen, candidates = set(), []
        for el in page.query_selector_all("a[href*='/p/']")[:40]:
            href = el.get_attribute("href") or ""
            if "/p/" not in href or href in seen:
                continue
            try:
                parent_text = el.evaluate(
                    "(el) => { let p = el.closest('div,li'); return p ? p.innerText : ''; }").lower()
            except Exception:
                parent_text = ""
            if any(w in parent_text for w in
                   ["replied","antwort","geantwortet","reply","comment","kommentar"]):
                seen.add(href)
                candidates.append("https://www.instagram.com" + href if href.startswith("/") else href)
        log(f"Found {len(candidates)} posts with possible replies")
        for url in candidates[:8]:
            if count >= LIMITS["replies"]:
                break
            pid = (re.search(r"/p/([^/]+)/", url) or [None, url])[1]
            if replied.get(pid, 0) >= 2:
                continue
            try:
                page.goto(url, timeout=30000)
                sleep(3, 5)
                comments = page.query_selector_all("article ul li, div[role='presentation'] li")
                our_idx, reply_text = None, None
                for i, c in enumerate(comments):
                    if "velluto" in c.inner_text().lower():
                        our_idx = i; break
                if our_idx is not None:
                    for j in range(our_idx + 1, min(our_idx + 5, len(comments))):
                        t = comments[j].inner_text().strip()
                        if len(t) > 5 and "velluto" not in t.lower():
                            reply_text = t[:200]; break
                if not reply_text:
                    continue
                log(f"  Reply found: '{reply_text[:60]}'")
                german = is_dach(reply_text)
                reply_comment = ai_reply(client, reply_text, german)
                api_calls[0] += 1
                if not validate_comment(reply_comment):
                    log(f"  SKIP reply — failed validation: '{reply_comment[:50]}'")
                    continue
                for c in comments:
                    if "velluto" in c.inner_text().lower():
                        rb = c.query_selector("button:has-text('Reply'), button:has-text('Antworten')")
                        if rb:
                            rb.click(timeout=3000)
                            sleep(1.5, 2.5)
                            if post_comment(page, reply_comment):
                                log(f'  Replied: "{reply_comment}"')
                                replied[pid] = replied.get(pid, 0) + 1
                                count += 1
                        break
            except Exception as e:
                log(f"  Reply error: {e}")
    except Exception as e:
        log(f"Reply phase error: {e}")
    return count


# ── Phase 2: Engagement (discovery-driven) ─────────────────────────────────────
def engagement(page, engaged, counts, results, client, api_calls, follows_ts,
               start_time, engaged_ts):
    visited_total   = 0
    posted_texts    = set()
    last_comment_at = 0.0

    seen_ids = {discovery.post_id(u) for u in []}  # (target-post dedup within discovery)
    want = MAX_TOTAL * 3   # over-fetch; many candidates get skipped downstream
    urls = discovery.discover(page, SEED_ACCOUNTS, LOCATION_IDS,
                              want=want, skip_users=SKIP | engaged,
                              seen_ids=seen_ids, log=log)
    log(f"\n── Engaging {len(urls)} candidate posts ──")

    for url in urls:
        if sum(counts.values()) >= MAX_TOTAL:
            break
        if time.time() - start_time > SESSION_MAX_SECS:
            log("⏱  SESSION_MAX_SECS reached — stopping"); break
        try:
            page.goto(url, timeout=30000)
            sleep(3, 5)
            dismiss_overlays(page)
            visited_total += 1

            username = get_username(page)
            if username in engaged or username in SKIP:
                continue

            caption  = get_caption(page)
            loc_el   = page.query_selector("a[href*='/explore/locations/']")
            location = loc_el.inner_text() if loc_el else ""
            german = False
            if _LANGDETECT_OK and len(caption.strip()) >= 20:
                try:
                    german = _langdetect(caption) == "de"
                except Exception:
                    german = is_dach(caption + " " + location)
            else:
                german = is_dach(caption + " " + location)
            lang = "DE" if german else "EN"

            if not quality_check(username):
                log(f"  SKIP @{username} — quality check"); continue

            has_caption = len(caption.strip()) >= 20
            log(f"  → @{username} [{lang}]{'  caption ✓' if has_caption else '  no caption'}")

            if DRY_RUN:
                # Prove discovery + AI work, take NO real action.
                would = ""
                if has_caption:
                    c = ai_comment(client, page, caption, german); api_calls[0] += 1
                    would = c if (c and validate_comment(c)) else "(invalid)"
                log(f"    DRY-RUN — would like/follow @{username}"
                    + (f' + comment: "{would}"' if has_caption else ""))
                results.append({"account": username, "hashtag": "discovery",
                                "like": "~", "comment": would if has_caption else "-",
                                "follow": "~", "lang": lang})
                engaged.add(username)
                sleep(4, 8)
                continue

            did_like = did_comment = did_follow = False
            comment_text = None

            if counts["likes"] < LIMITS["likes"]:
                svg = page.query_selector("svg[aria-label='Like'],svg[aria-label='Gefällt mir']")
                if svg:
                    svg.click(timeout=5000); counts["likes"] += 1; did_like = True
                    log("    ✓ Like"); sleep(30, 60)

            _now_ts = time.time()
            _cooldown_ok = (_now_ts - last_comment_at) >= COMMENT_COOLDOWN
            if not _cooldown_ok and has_caption and counts["comments"] < LIMITS["comments"]:
                log(f"    SKIP comment — cooldown ({int(COMMENT_COOLDOWN-(_now_ts-last_comment_at))}s left)")
            if has_caption and counts["comments"] < LIMITS["comments"] and _cooldown_ok:
                if already_commented(page):
                    log("    SKIP comment — already commented on this post")
                else:
                    comment_text = ai_comment(client, page, caption, german); api_calls[0] += 1
                    if comment_text and comment_text in posted_texts:
                        log("    retry — duplicate comment text, regenerating")
                        comment_text = ai_comment(client, page, caption, german); api_calls[0] += 1
                    if (comment_text and validate_comment(comment_text)
                            and comment_text not in posted_texts):
                        if post_comment(page, comment_text):
                            posted_texts.add(comment_text); counts["comments"] += 1
                            did_comment = True; last_comment_at = time.time()
                            log(f'    "{comment_text}"')
                    else:
                        log("    no comment — AI output invalid or duplicate")

            if counts["follows"] < LIMITS["follows"]:
                if click_follow_btn(page):
                    counts["follows"] += 1; did_follow = True; log("    ✓ Follow")

            if did_follow:
                follows_ts[username] = datetime.now().isoformat()
                save_json(FOLLOWS_FILE, follows_ts)

            if did_like or did_comment or did_follow:
                engaged.add(username)
                engaged_ts[username] = datetime.now().isoformat()
                save_json(ENGAGED_FILE, engaged_ts)
                results.append({"account": username, "hashtag": "discovery",
                                "like": "✓" if did_like else "-",
                                "comment": comment_text if did_comment else "-",
                                "follow": "✓" if did_follow else "-", "lang": lang})
            sleep(8, 15)
        except PWTimeout:
            log("  timeout — skip")
        except Exception as e:
            log(f"  err: {e}")
    return visited_total


# ── E-Mail summary ─────────────────────────────────────────────────────────────
def send_email(subject, body):
    if not EMAIL_FROM or not EMAIL_APP_PASS:
        log("E-Mail skip — EMAIL_FROM / EMAIL_APP_PASS not set in .env"); return
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject; msg["From"] = EMAIL_FROM; msg["To"] = EMAIL_TO
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
            s.starttls(); s.login(EMAIL_FROM, EMAIL_APP_PASS); s.send_message(msg)
        log(f"✉ Summary sent to {EMAIL_TO}")
    except Exception as e:
        log(f"E-Mail error: {e}")

def build_daily_email():
    today = datetime.now().strftime("%Y-%m-%d")
    lines = []
    try:
        raw = SUMMARY_FILE.read_text()
        in_block, block = False, []
        for line in raw.splitlines():
            if f"SESSION SUMMARY — {today}" in line:
                in_block = True; block = [line]
            elif in_block:
                block.append(line)
                if line.startswith("═" * 10):
                    lines.extend(block); lines.append(""); in_block = False
    except Exception:
        lines.append("(kein Summary verfügbar)")
    lines.append("")
    try:
        opt = OPTIMIZE_FILE.read_text()
        today_opt = [l for l in opt.splitlines() if today in l]
        if today_opt:
            lines.append("── Optimization ──"); lines.extend(today_opt)
    except Exception:
        pass
    return "\n".join(lines)

def log_optimization(session_num, duration_s, visited, engaged_count, api_calls):
    try:
        cpu_raw = subprocess.run(["sh","-c",
            "grep 'cpu ' /proc/stat | awk '{u=$2+$4; t=$2+$3+$4+$5; print int(u*100/t)}'"],
            capture_output=True, text=True, timeout=5).stdout.strip()
        mem_raw = subprocess.run(["sh","-c",
            "free -m | awk 'NR==2{printf \"%d\", $3*100/$2}'"],
            capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        cpu_raw, mem_raw = "?", "?"
    efficiency = f"{(engaged_count / visited * 100):.1f}" if visited else "0"
    line = (f"{datetime.now().strftime('%Y-%m-%d %H:%M')} | S{session_num} | "
            f"Dauer: {int(duration_s//60)}min | Besucht: {visited} | Engaged: {engaged_count} | "
            f"API: {api_calls} calls | CPU: {cpu_raw}% | MEM: {mem_raw}% | Effizienz: {efficiency}%")
    with open(OPTIMIZE_FILE, "a") as f:
        f.write(line + "\n")
    log(f"📊 {line}")


def unfollow_oldest(page, n, follows_ts):
    if not follows_ts:
        log("  No follows to unfollow yet"); return 0
    unfollowed = 0
    for username, _ in sorted(follows_ts.items(), key=lambda x: x[1])[:n]:
        try:
            page.goto(f"https://www.instagram.com/{username}/", timeout=20000)
            sleep(3, 5)
            found = False
            for btn in page.query_selector_all("button, div[role='button']"):
                try:
                    if btn.inner_text().strip() in ("Following", "Abonniert", "Folge ich"):
                        btn.click(timeout=5000); sleep(1, 2)
                        for b2 in page.query_selector_all("button, div[role='button']"):
                            try:
                                if b2.inner_text().strip() in ("Unfollow","Entfolgen","Nicht mehr folgen"):
                                    b2.click(timeout=5000); del follows_ts[username]
                                    save_json(FOLLOWS_FILE, follows_ts); unfollowed += 1
                                    log(f"  ✓ Unfollow @{username}"); sleep(10, 20)
                                    found = True; break
                            except Exception:
                                pass
                        break
                except Exception:
                    pass
            if not found:
                log(f"  skip unfollow @{username} — button not found")
        except Exception as e:
            log(f"  unfollow error @{username}: {e}")
    return unfollowed


def debug_profile(handle: str):
    """Diagnostic: load ONE profile and dump everything needed to tell WHY
    discovery finds 0 posts — final URL, title, block markers, DOM vs. raw-HTML
    shortcode counts, plus a screenshot + HTML dump in logs/. One profile visit,
    not sixteen, so it's safe to run even on a throttled account."""
    handle = (handle or "").strip().lstrip("@").strip("/")
    LOG_DIR.mkdir(exist_ok=True)
    log("═" * 46)
    log(f"DEBUG PROFILE @{handle} — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    cookies = json.loads(COOKIES_FILE.read_text())
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                  "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"),
            viewport={"width": 1280, "height": 900}, locale="de-DE")
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.goto("https://www.instagram.com/", timeout=30000)
        sleep(4, 6)
        if "login" in page.url:
            log("ERROR: homepage redirected to login — session.json is stale, re-upload it")
            browser.close(); return
        log("✓ Logged in (homepage)")

        page.goto(f"https://www.instagram.com/{handle}/", timeout=30000,
                  wait_until="domcontentloaded")
        sleep(5, 7)
        discovery._dismiss(page)
        for _ in range(4):
            try:
                page.evaluate("window.scrollBy(0, 900)")
            except Exception:
                break
            sleep(1.2, 2.0)

        final_url = page.url
        try:    title = page.title()
        except Exception: title = ""
        try:    html = page.content()
        except Exception: html = ""
        anchors  = page.query_selector_all("a[href]")
        p_dom    = sum(1 for el in anchors if "/p/"    in (el.get_attribute("href") or ""))
        reel_dom = sum(1 for el in anchors if "/reel/" in (el.get_attribute("href") or ""))
        rx_url   = len(set(m[1] for m in discovery._HTML_CODE_RE.findall(html)))
        rx_json  = len(set(discovery._JSON_CODE_RE.findall(html)))
        low = (final_url + " " + title + " " + html[:3000]).lower()
        markers = [m for m in ("login", "challenge", "suspended", "try again",
                               "something went wrong", "confirm", "not available",
                               "couldn't refresh", "captcha", "restricted")
                   if m in low]

        png   = LOG_DIR / f"debug_{handle}.png"
        htmlf = LOG_DIR / f"debug_{handle}.html"
        try:    page.screenshot(path=str(png))
        except Exception as e: log(f"  screenshot failed: {e}")
        try:    htmlf.write_text(html)
        except Exception as e: log(f"  html dump failed: {e}")

        log(f"  final url : {final_url}")
        log(f"  title     : {title[:80]}")
        log(f"  anchors   : {len(anchors)} total | /p/ DOM: {p_dom} | /reel/ DOM: {reel_dom}")
        log(f"  raw html  : {rx_url} p/reel shortcodes | {rx_json} json code keys | {len(html)} bytes")
        log(f"  markers   : {markers or 'none'}")
        log(f"  saved     : logs/{png.name}, logs/{htmlf.name}")

        if any(x in final_url.lower() for x in ("/login", "/challenge", "/suspended")):
            log("  VERDICT   : redirect → cookie stale / action-block. No code fix — "
                "slow down / re-mint session.json.")
        elif p_dom == 0 and reel_dom == 0 and rx_url == 0 and rx_json == 0:
            log("  VERDICT   : no post data in the payload → throttle/block or pure app-shell. "
                "Slow down / re-mint session.json.")
        elif p_dom == 0 and reel_dom == 0 and (rx_url > 0 or rx_json > 0):
            log("  VERDICT   : data present but NOT in DOM anchors → the regex/JSON fallback "
                "handles this; re-run the dry-run.")
        else:
            log("  VERDICT   : DOM anchors present → discovery should work; likely overlay/timing "
                "(the new dismiss + wait should fix it).")
        browser.close()


def run(session_num: int):
    start_time = time.time()
    log("═" * 46)
    log(f"Session {session_num}{' [DRY-RUN]' if DRY_RUN else ''} — {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    cookies = json.loads(COOKIES_FILE.read_text())
    _now = datetime.now()
    _engaged_raw = load_json(ENGAGED_FILE, {})
    if isinstance(_engaged_raw, list):
        _engaged_raw = {u: _now.isoformat() for u in _engaged_raw}
    engaged_ts = {u: ts for u, ts in _engaged_raw.items()
                  if (_now - datetime.fromisoformat(ts)).days < ENGAGE_TTL_DAYS}
    engaged = set(engaged_ts.keys())
    log(f"Engaged cache: {len(engaged)} accounts (TTL {ENGAGE_TTL_DAYS}d)")
    replied = {k: (v if isinstance(v, int) else 1) for k, v in load_json(REPLIED_FILE, {}).items()}
    follows_ts = load_json(FOLLOWS_FILE, {})
    client = anthropic.Anthropic(api_key=API_KEY)
    api_calls = [0]
    counts = {"likes": 0, "comments": 0, "follows": 0, "unfollows": 0}
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu",
                  "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"),
            viewport={"width": 1280, "height": 900}, locale="de-DE")
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        page.goto("https://www.instagram.com/", timeout=30000)
        sleep(4, 6)
        if "login" in page.url:
            log("ERROR: Not logged in — re-upload session.json"); browser.close(); sys.exit(1)
        log("✓ Logged in")

        reply_count = 0
        if not DRY_RUN:
            reply_count = check_replies(page, client, replied, api_calls)
            log("── Unfollowing oldest ──")
            counts["unfollows"] = unfollow_oldest(page, LIMITS["unfollows"], follows_ts)
        visited_total = engagement(page, engaged, counts, results, client,
                                   api_calls, follows_ts, start_time, engaged_ts)
        browser.close()

    if not DRY_RUN:
        save_json(ENGAGED_FILE, engaged_ts)
        save_json(REPLIED_FILE, replied)

    total = sum(counts.values())
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = ["", "═"*46, f"SESSION SUMMARY{' [DRY-RUN]' if DRY_RUN else ''} — {ts}",
             f"Session {session_num}  |  Likes: {counts['likes']}  Comments: {counts['comments']}  "
             f"Follows: {counts['follows']}  Unfollows: {counts.get('unfollows',0)}  "
             f"Replies: {reply_count}  Total: {total}", "─"*46]
    for r in results:
        if r["comment"] not in ("-", None):
            lines.append(f"@{r['account']:<22} [{r['lang']}] \"{r['comment']}\"")
        else:
            lines.append(f"@{r['account']:<22} [{r['lang']}] liked"
                         + (' + followed' if r['follow'] == '✓' else ''))
    lines.append("═"*46)
    summary = "\n".join(lines)
    print(summary, flush=True)
    if not DRY_RUN:
        with open(SUMMARY_FILE, "a") as f:
            f.write(summary + "\n")
    for line in lines:
        log(line)

    log_optimization(session_num, time.time() - start_time, visited_total, total, api_calls[0])

    if session_num == 3 and not DRY_RUN:
        send_email(f"📊 Velluto Instagram — Daily Summary {datetime.now().strftime('%Y-%m-%d')}",
                   build_daily_email())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true",
                        help="discover + log candidates, take NO actions")
    parser.add_argument("--debug-profile", metavar="HANDLE", default=None,
                        help="diagnose ONE profile (why discovery finds 0 posts), take NO actions")
    args = parser.parse_args()
    if args.debug_profile:
        debug_profile(args.debug_profile)
    else:
        DRY_RUN = args.dry_run
        run(args.session)
