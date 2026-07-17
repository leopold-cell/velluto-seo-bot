# Velluto Instagram Engagement Bot

Playwright cookie-session bot that engages (like / AI-comment / follow / reply /
unfollow) with active cyclists and emails a daily summary. It replaces the old
standalone project at `/root/velluto/instagram/`, which broke when Instagram
killed the hashtag grids it relied on for finding posts.

> ⚠️ **ToS / ban risk.** Automated engagement violates Instagram's Terms and can
> get the account action-blocked or banned. Keep the limits modest, keep the
> human-paced sleeps, and watch the daily summary for action-blocks. This is a
> maintenance treadmill, not fire-and-forget.

## What changed vs. the old bot (the fix)

Instagram made `/explore/tags/{hashtag}/` return **0 posts** to logged-in
automation, so the old grid scrape (`a[href*='/p/']`) found nothing — that's why
it went silent. Discovery was rebuilt (`discovery.py`):

1. **Seed-account engagers (primary):** open a cycling account's recent posts and
   read the **commenters** (comment lists still render in the DOM; like lists are
   hidden). People who comment on cycling content are real, active cyclists — we
   engage with their own latest post.
2. **Location grids (secondary):** `/explore/locations/{id}/` grids for cycling
   hotspots are far less restricted than hashtag grids.

Everything downstream (like/comment/follow/reply/unfollow, daily email, optimize
log) is unchanged. Tune discovery in `config.py` (`SEED_ACCOUNTS`, `LOCATION_IDS`).

## Files

| File | Purpose |
|------|---------|
| `bot.py` | Main bot. `--session 1\|2\|3`, `--dry-run`. |
| `discovery.py` | Rebuilt post discovery (seed engagers + locations). |
| `config.py` | `SEED_ACCOUNTS` / `LOCATION_IDS` — edit to tune targeting. |
| `run_ig.sh` | Cron wrapper: lockfile + session-by-hour + venv + git pull. |
| `requirements.txt` | Extra deps on top of the repo-root venv. |

Local-only (git-ignored, live only on the VPS): `session.json`, `engaged.json`,
`replied.json`, `follows.json`, `summaries.log`, `optimization.log`, `logs/`.

## Setup (VPS)

The bot runs inside the repo-root `venv`. From `.../velluto-seo-bot`:

```bash
source venv/bin/activate
pip install -r instagram_engagement/requirements.txt
python3 -m playwright install chromium     # first time only
```

### 1. Login cookie — `session.json`

The bot logs in via a saved Playwright storage-state cookie (no password in code).
Reuse the existing cookie from the old project, or mint a fresh one on a machine
with a browser:

```python
# save_session.py — run locally where you can see a browser, then copy the file up
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=False)
    pg = b.new_context(locale="de-DE").new_page()
    pg.goto("https://www.instagram.com/accounts/login/")
    input("Log in manually in the window, then press Enter here… ")
    pg.context.cookies()  # warm
    import json; json.dump(pg.context.cookies(), open("session.json", "w"))
    b.close()
```

Then place it next to `bot.py`:

```bash
cp /root/velluto/instagram/session.json instagram_engagement/session.json
```

If the login is stale the bot logs `Not logged in — re-upload session.json` and
exits; re-mint the cookie.

### 2. Carry over runtime state (optional but recommended)

Preserves the "already engaged / already followed" memory so the bot doesn't
re-hit the same accounts:

```bash
cp /root/velluto/instagram/{engaged,replied,follows}.json instagram_engagement/ 2>/dev/null || true
```

### 3. Environment

The bot reads these from the environment (the repo-root `.env` is loaded by the
cron shell, or export them). Reuses the SEO pipeline's Gmail app-password:

```
ANTHROPIC_API_KEY=sk-ant-…
EMAIL_FROM=<gmail address>
EMAIL_APP_PASS=<gmail app password>
EMAIL_TO=leopold@velluto-brand.com     # default if unset
```

## Verify before going live

**Always dry-run first** — proves the new discovery finds posts without taking a
single action (the whole point of the rebuild):

```bash
cd instagram_engagement
python3 -u bot.py --session 1 --dry-run
```

Look for `discovery: N candidate posts collected` with **N > 0** and a list of
`DRY-RUN — would like/follow @…` lines.

### If discovery finds 0 posts — diagnose ONE profile first

Instagram churns its DOM and throttles automation, so a `0 candidate posts` run
needs a diagnosis, not a guess. `--debug-profile` loads **one** profile (safe on
a throttled account) and tells you exactly why:

```bash
python3 -u bot.py --debug-profile gcn
```

It logs the final URL, page title, block markers, and — critically — how many
post shortcodes are in the **DOM anchors** vs. the **raw HTML/JSON**, then prints
a `VERDICT`. It also saves `logs/debug_gcn.png` + `logs/debug_gcn.html` to eyeball.

| VERDICT | Meaning | Action |
|---------|---------|--------|
| redirect → login/challenge | cookie stale or account action-blocked | re-mint `session.json`, slow down — **no code fix helps** |
| no post data in payload | throttle/block or pure app-shell | slow down / re-mint `session.json` |
| data present but not in DOM anchors | IG changed the grid DOM | the regex/JSON fallback already handles it — just re-run the dry-run |
| DOM anchors present | should work | overlay/timing — the built-in dismiss + wait should fix it |

Cross-check manually: open those same profiles in a normal browser **logged in as
this account** — if you can't see their posts there either, the account is
restricted (a people problem, not a code one).

Then one live session at the conservative default limits and check the summary
email.

## Cron (reactivate the schedule)

The old crontab had these lines **commented out** and pointing at a `run.sh1`
typo. Replace them with the wrapper here (3 sessions/day; session 3 sends the
email). Adjust hours to taste — spread them out and keep them human-ish:

```cron
# Velluto Instagram engagement — 3 sessions/day
30 8  * * * /root/velluto/velluto-seo-bot/instagram_engagement/run_ig.sh >> /root/velluto/velluto-seo-bot/instagram_engagement/logs/cron.log 2>&1
15 14 * * * /root/velluto/velluto-seo-bot/instagram_engagement/run_ig.sh >> /root/velluto/velluto-seo-bot/instagram_engagement/logs/cron.log 2>&1
45 19 * * * /root/velluto/velluto-seo-bot/instagram_engagement/run_ig.sh >> /root/velluto/velluto-seo-bot/instagram_engagement/logs/cron.log 2>&1
```

`run_ig.sh` derives the session number from the hour (before 12 → 1, 12–17 → 2,
18+ → 3), holds a lockfile so two sessions can't overlap, and pulls the latest
code before running. Force a specific session with `run_ig.sh 2` or a safe check
with `run_ig.sh --dry-run`.

## Tuning

- **Ban-safe re-warming:** limits start conservative
  (`LIMITS = likes 12 / comments 8 / follows 6 / unfollows 6 / replies 5`,
  `MAX_TOTAL = 26`, 15-min session cap, 60s comment cooldown). Raise slowly only
  once the account has run clean for a couple of weeks.
- **Targeting:** edit `SEED_ACCOUNTS` in `config.py` toward your real audience
  (more DACH/NL/FR accounts = more home-market commenters). Add cycling-hotspot
  `LOCATION_IDS` for a secondary source.
