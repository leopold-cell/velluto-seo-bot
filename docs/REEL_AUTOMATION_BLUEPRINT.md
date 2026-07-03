# Instagram Reel Automation — Generic Implementation Blueprint

> **Purpose:** A self-contained spec for building a fully automated Instagram Reels
> pipeline in a fresh project. Hand this file to a Claude (Code) session and say
> "implement this". Everything brand-specific is a `{{PLACEHOLDER}}` — fill in the
> table below first. This blueprint was extracted from a production system posting
> 3 reels/day; the **Pitfalls** section encodes every failure mode that was hit and
> fixed on the way, so read it before writing code.

---

## 1. What the pipeline does

Every day, at `{{POSTING_TIMES}}` (default: 3 slots — morning/noon/evening), the
system autonomously:

1. Picks a **vetted video clip** from a Google Drive folder (auto-discovery — drop a
   new clip in Drive and it enters the rotation; no code change).
2. Asks **Claude** for a fresh piece of on-screen text + an Instagram caption in the
   configured `{{CONTENT_STYLE}}` for the `{{NICHE}}` audience.
3. **Burns the text overlay** onto the clip (native-look white text, Pillow + ffmpeg),
   mixes in a **license-free music track** (also rotated from a Drive folder), and
   standardizes the reel to exactly `{{REEL_SECONDS}}` seconds (short clips loop,
   long clips trim).
4. Uploads the finished video to Google Drive (public direct-download URL).
5. Publishes it as a **normal Reel** to `{{IG_HANDLE}}` via the official Instagram
   Graph API.
6. Emails `{{ALERT_EMAIL}}` **only when something fails** (clean runs are silent).

```
Drive clips folder ──┐
Drive music folder ──┤
                     ▼
   Claude brief ──► caption_engine (Pillow overlay + ffmpeg composite, {{REEL_SECONDS}}s)
                     │
                     ▼
   drive_upload (public URL) ──► ig_publisher (Graph API REELS) ──► posted
                     │
                     └── on any failure ──► alert email
```

**Design principles (keep these):**
- *Deterministic footage, generated words.* Reuse a human-vetted clip library and
  change only the text daily — never gamble on daily AI video generation.
- *Never post a broken artifact.* No caption burned → no post. Upload failed → no post.
- *Silent success, loud failure.* Email only on problems.
- *Switches, not counts.* `IG_AUTOPOST=1` arms posting; cadence comes from cron.

---

## 2. Placeholders — fill these in first

| Placeholder | Meaning | Example |
|---|---|---|
| `{{BRAND}}` | Brand name (background vibe only, never pitched in content) | Acme |
| `{{IG_HANDLE}}` | Instagram business account handle | @acme.official |
| `{{NICHE}}` | The community/subculture the content lives in | trail running |
| `{{AUDIENCE_PERSONA}}` | Who must think "that's literally me" | amateur trail runners who race on weekends |
| `{{CONTENT_STYLE}}` | The fixed reel formula (see §6 for the proven template) | faceless POV + one held text line + end punchline |
| `{{INSIDE_JOKES}}` | 8–12 niche-specific relatable tropes for the prompt | gear obsession, "easy run" lies, race-day rituals, … |
| `{{HASHTAGS}}` | Fixed hashtag set appended to EVERY caption | #trailrunning #running … |
| `{{REEL_SECONDS}}` | Standardized reel length (5–90 allowed; 8–15 works well) | 14 |
| `{{POSTING_TIMES}}` | Cron times, one per slot | 08:00, 13:00, 19:00 |
| `{{TIMEZONE}}` | Server timezone the slots are computed in | Europe/Berlin |
| `{{ALERT_EMAIL}}` | Failure-alert recipient | you@example.com |
| `{{CLIPS_FOLDER_ID}}` | Drive folder ID with vetted source clips (9:16, ≥ reel length ideal) | 1AbC… |
| `{{MUSIC_FOLDER_ID}}` | Drive folder ID with license-free MP3s | 1DeF… |
| `{{OUTPUT_FOLDER_ID}}` | Drive folder ID for finished reels | 1GhI… |

---

## 3. Meta / Instagram setup (one-time, manual)

Prereq: `{{IG_HANDLE}}` is an **Instagram Business account** linked to a **Facebook
Page** you admin.

1. **Create a Meta app** at developers.facebook.com (type: Business). Note App ID +
   App Secret → `FB_APP_ID`, `FB_APP_SECRET`.
2. **If the Page lives in a Business Portfolio** (business.facebook.com): the Page
   will NOT appear in `/me/accounts`. Fix: Business Settings → Accounts → Apps → add
   your app → **"Assign assets"** → link the Page (+ IG account). Also note the
   numeric **Page ID** → `FB_PAGE_ID` (bypasses `/me/accounts` entirely — the most
   reliable path).
3. **Generate a short-lived user token** in the Graph API Explorer with scopes:
   `instagram_basic, instagram_content_publish, pages_show_list,
   pages_read_engagement, business_management`. In the consent popup, **approve every
   permission** — added-but-not-granted scopes are the #1 cause of cryptic errors.
   Verify with `GET /me/permissions` (each must say `"granted"`).
4. **Bootstrap script** (`instagram_auth.py`, run once, interactive):
   - exchange short-lived → long-lived user token (`GET /oauth/access_token` with
     `grant_type=fb_exchange_token`);
   - fetch the Page directly: `GET /{FB_PAGE_ID}?fields=name,access_token,
     instagram_business_account` (fall back to `/me/accounts`, then to
     `/me/businesses/{id}/owned_pages` for portfolio setups);
   - if the `instagram_business_account` lookup fails with the page token, **retry
     with the user token** (portfolio pages sometimes only answer to it);
   - write `IG_ACCESS_TOKEN` (page token — effectively non-expiring) and
     `IG_USER_ID` (the IG business account id) to `.env`.

---

## 4. Google Drive setup (one-time, manual)

Auth is **user OAuth with a refresh token — NOT a service-account key** (org policies
often block SA key creation, and OAuth uploads use the user's normal quota, so plain
"My Drive" folders work).

1. Google Cloud Console → project → enable **Google Drive API**.
2. Create an **OAuth client** (type: Web application) with redirect URI
   `https://developers.google.com/oauthplayground` → `GOOGLE_DRIVE_CLIENT_ID/SECRET`.
3. **OAuth consent screen → publish to Production.** (In "Testing" status refresh
   tokens silently expire after 7 days — a guaranteed future outage.)
4. **OAuth Playground** (developers.google.com/oauthplayground) → gear icon:
   *Use your own OAuth credentials* (paste client id + secret), *OAuth flow:
   Server-side*, *Access type: Offline*, *Force prompt: Consent Screen*. Scopes —
   BOTH, space-separated:
   `https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.metadata.readonly`
   (`drive.file` = upload own files; `metadata.readonly` = list the input folders
   for auto-discovery). Authorize → **Exchange authorization code for tokens** → copy
   the **`refresh_token` (starts `1//`)** → `GOOGLE_DRIVE_REFRESH_TOKEN`.
5. Create three Drive folders (clips / music / output), share the two **input**
   folders' files as "anyone with the link", note all three folder IDs.

Sanity check the token from the server:
```python
r = requests.post("https://oauth2.googleapis.com/token", data={
    "client_id": CID, "client_secret": CSEC,
    "refresh_token": RTOKEN, "grant_type": "refresh_token"})
assert r.status_code == 200   # invalid_grant → token minted with a DIFFERENT client
```

---

## 5. Module specs

Target layout (single repo, one venv):
```
reel_brief.py       # orchestrator (slots, sourcing, guards, email policy)
caption_video.py    # download + overlay + music + standardize
drive_upload.py     # OAuth upload + folder listing (auto-discovery)
instagram_post.py   # Graph API publisher
instagram_auth.py   # one-time token bootstrap (§3)
mailer.py           # SMTP email (attachments supported)
run_reel.sh         # cron entrypoint (activates venv!)
requirements.txt    # anthropic requests python-dotenv Pillow imageio-ffmpeg
                    # google-api-python-client google-auth google-auth-oauthlib
```

### 5.1 `caption_video.py` — the caption/compositing engine

**ffmpeg resolution — always prefer the pip-bundled binary** (old system ffmpeg
mishandles the filters below):
```python
def _ffmpeg() -> str:
    env = os.getenv("FFMPEG_BIN", "").strip()
    if env and os.path.isfile(env):
        return env
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg") or ""
```

**Drive-robust download** — large Drive files return an HTML virus-scan interstitial
from `uc?export=download`, which naive code saves as a corrupt "mp4":
```python
def download(url: str, dest: str) -> bool:
    sess = requests.Session()
    fid = _drive_id(url) if "google.com" in url else ""   # regex /d/<id> or ?id=<id>
    target = (f"https://drive.usercontent.google.com/download?id={fid}"
              f"&export=download&confirm=t") if fid else url
    r = sess.get(target, stream=True, timeout=180, allow_redirects=True)
    r.raise_for_status()
    if "text/html" in r.headers.get("content-type", "").lower():
        # still the scan-warning page → submit its form
        action = re.search(r'action="([^"]+)"', r.text)
        fields = dict(re.findall(r'name="([^"]+)"\s+value="([^"]*)"', r.text))
        r = sess.get(html.unescape(action.group(1)), params=fields, stream=True, timeout=180)
        r.raise_for_status()
    # ... stream to dest ...
    head = open(dest, "rb").read(64).lstrip()
    return head[:1] != b"<" and os.path.getsize(dest) > 20000   # reject HTML/stub
```

**Overlay rendering (Pillow → transparent 1080×1920 PNG).** Native Instagram look:
plain **white bold text with a thin black stroke, no background panel**. Main line
centered in the upper third (held the WHOLE clip — the joke lives in the text);
optional punchline lower third, also white. Wrap by measuring `draw.textlength()`
against ~86% of canvas width; font ~82px main / ~66px punchline
(DejaVuSans-Bold or equivalent); `stroke_width≈6, stroke_fill=black`.

**Composite + standardize** — normalize ANY input format, loop short clips, hard-cut
to `{{REEL_SECONDS}}`:
```python
vf = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
      "crop=1080:1920,setsar=1,fps=30[base];[base][1:v]overlay=0:0[v]")
cmd = [ffmpeg, "-y", "-stream_loop", "-1", "-i", raw_clip, "-i", overlay_png]
if music:  cmd += ["-stream_loop", "-1", "-i", music_mp3]
cmd += ["-filter_complex", vf, "-map", "[v]"]
if music:  cmd += ["-map", "2:a", "-c:a", "aac", "-b:a", "160k"]
cmd += ["-t", f"{REEL_SECONDS:.3f}",           # deterministic cut, video AND audio
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", out_path]
```
Contract: return the captioned path on success, the `*_raw.mp4` path on failure —
callers detect the `_raw` suffix and **refuse to post**.

### 5.2 `drive_upload.py` — hosting + auto-discovery

- Build credentials from `GOOGLE_DRIVE_CLIENT_ID/SECRET + GOOGLE_DRIVE_REFRESH_TOKEN`
  (`google.oauth2.credentials.Credentials`, token_uri `https://oauth2.googleapis.com/token`).
- `upload_public(path)` → `files().create` into `{{OUTPUT_FOLDER_ID}}` →
  `permissions().create(type=anyone, role=reader)` → return
  `https://drive.google.com/uc?export=download&id={id}`.
- `list_folder_files(folder_id, mime)` → `files().list` with
  `q="'{id}' in parents and mimeType contains '{mime}' and trashed=false"`,
  `orderBy="name"`, paginate. Used with `mime="video/"` (clips) and `"audio/"` (music).
- Everything returns `""`/`[]` on failure and logs — a broken Drive setup must never
  crash the pipeline (posting is simply skipped and alerted).

### 5.3 `instagram_post.py` — the publisher (normal Reels)

Three-step Graph API flow (`https://graph.facebook.com/v21.0`):
```python
# 1) create container
r = requests.post(f"{GRAPH}/{IG_USER_ID}/media", data={
    "media_type": "REELS", "video_url": public_url, "caption": caption,
    "share_to_feed": "true",              # normal reel, full audience + feed/grid
    "access_token": IG_ACCESS_TOKEN}, timeout=60).json()
container_id = r["id"]
# 2) poll until Meta finishes ingesting (async transcode of video_url)
#    GET /{container_id}?fields=status_code  → wait for FINISHED
#    (poll ~every 6s, ~30 tries; ERROR/EXPIRED → abort + alert)
# 3) publish
requests.post(f"{GRAPH}/{IG_USER_ID}/media_publish", data={
    "creation_id": container_id, "access_token": IG_ACCESS_TOKEN})
```
Rules:
- `IG_AUTOPOST` env gates real posting: unset/0 → **dry-run** (log what would post).
- **Never post without a burned caption** (check the `_raw` suffix contract).
- `video_url` must be publicly fetchable by Meta → the Drive public link from 5.2.
- Reel specs: 9:16, 5–90 s, H.264, ≥ 1080×1920 recommended.
- *Optional variant:* Instagram also supports "trial reels" (shown only to
  non-followers first) by adding `trial_params={"graduation_strategy":"MANUAL"}`
  to step 1 — not used by default in this blueprint.

### 5.4 `reel_brief.py` — brief generator + orchestrator

**Slot logic** (3 posts/day, one per slot, different content per slot):
```python
def _current_slot():                      # ({{TIMEZONE}} local hour)
    h = datetime.datetime.now().hour
    return ("morning", 0) if h < 11 else ("noon", 1) if h < 16 else ("evening", 2)

def _slot_seed():                          # unique per (day, slot)
    return datetime.date.today().toordinal() * 3 + _current_slot()[1]
```
- Rotate clips/music with `urls[_slot_seed() % len(urls)]`.
- **State guard** (`reel_state.json`: `{"date": today, "slots": [...]}`): skip if this
  slot already posted today; record **only successful posts** (dry-runs never block).
  `REEL_FORCE=1` env bypasses the guard for manual tests — it is a test switch, never
  set permanently.

**Sourcing:** clips = Drive folder auto-discovery (5.2), fallback to a committed
`reel_clips.json` URL list; same for music. Optional deeper fallback: generate a clip
via an AI video API — only if the library is empty; vetted footage is the reliable path.

**Claude brief** — one call per reel (any capable model; temperature 1.0,
max_tokens ~900). System prompt template:
```
You create Instagram Reels for {{NICHE}} in this fixed format: {{CONTENT_STYLE}}.
• FACELESS footage; the whole joke lives in ONE big on-screen text line that stays
  up the entire clip — a relatable first-person thought of {{AUDIENCE_PERSONA}}.
  Optionally a short punchline flips it at the very end.
• Voice: dry, self-deprecating, insider. Real {{NICHE}} culture: {{INSIDE_JOKES}}.
This is NOT marketing: NO product pitch, NO features, NO CTA. {{BRAND}} stays a
background vibe, never mentioned. ONE goal: the viewer thinks "that's literally me"
and tags a friend or comments.
```
User prompt — demand EXACTLY these labelled blocks:
```
ONSCREEN: <the one held text line, first-person, max ~12 words,
           plain text only — NO meta-labels like 'narrator:', 'me:', 'pov:'>
PUNCHLINE: <optional payoff for the final ~2s, max ~8 words, or '-'>
CAPTION: <ONE single line, relatable, comment-baiting — ideally ends with a
          QUESTION. No links, no product talk, no hashtags (added automatically)>
```
Post-processing (models WILL violate instructions occasionally — enforce in code):
- `_extract(label, text)` via regex `LABEL:\s*(.+?)(?=\n[A-Z_]+:|\Z)`; strip stray
  `<>` template markers and quotes.
- `_strip_meta()`: regex-remove leading `narrator:|me:|pov:|caption:` etc.
- Caption: collapse to one line (`" ".join(s.split())`) then append `\n\n{{HASHTAGS}}`.

**Email policy:** collect problems (no clip, caption failed, upload failed, publish
failed while armed, brief generation failed) → send ONE alert email with details
(attach the video if present). No problems → print a one-line success log, **no email**.

### 5.5 `run_reel.sh` + cron

```bash
#!/bin/bash
cd /path/to/project || exit 1
git pull --rebase --autostash origin main >/dev/null 2>&1 || git rebase --abort 2>/dev/null
source venv/bin/activate          # CRITICAL — see Pitfalls
python3 reel_brief.py || echo "reel run failed"
```
```cron
0 8  * * * /path/to/project/run_reel.sh >> /var/log/reel.log 2>&1
0 13 * * * /path/to/project/run_reel.sh >> /var/log/reel.log 2>&1
0 19 * * * /path/to/project/run_reel.sh >> /var/log/reel.log 2>&1
```
(Times must fall inside the matching slot windows: <11 / <16 / rest.)

---

## 6. Proven content formula (fill `{{CONTENT_STYLE}}` with this)

The engagement-tested formula (modeled on top meme/relatable accounts):
1. **Faceless POV footage** from inside the activity — calm, authentic, no people
   performing to camera. Real user footage >> AI-generated video (image-to-video
   morphs and reads as fake).
2. **ONE held text line** = the entire joke. First person, hyper-specific to the
   niche ("me telling myself X for the 4th day in a row"). Not generic.
3. **Optional punchline** in the last ~2 s that flips or confirms the line.
4. **Caption = one line + question** to bait comments ("be honest — how many of you…?"),
   then the fixed `{{HASHTAGS}}`.
5. License-free music baked into the file (Instagram's music library is NOT
   available via the API — audio must be in the video).

---

## 7. `.env` template

```bash
# ── Claude (brief generation)
ANTHROPIC_API_KEY=

# ── Instagram / Meta (from §3)
FB_APP_ID=
FB_APP_SECRET=
FB_PAGE_ID=                    # numeric Page ID — most reliable resolution path
IG_ACCESS_TOKEN=               # written by instagram_auth.py
IG_USER_ID=                    # written by instagram_auth.py
IG_AUTOPOST=0                  # 0/unset = dry-run; 1 = actually publish. A SWITCH, not a count.

# ── Google Drive (from §4)
GOOGLE_DRIVE_CLIENT_ID=
GOOGLE_DRIVE_CLIENT_SECRET=
GOOGLE_DRIVE_REFRESH_TOKEN=    # starts with 1//  (ya29… is the WRONG token)
GDRIVE_CLIPS_FOLDER_ID={{CLIPS_FOLDER_ID}}
GDRIVE_MUSIC_FOLDER_ID={{MUSIC_FOLDER_ID}}
GDRIVE_FOLDER_ID={{OUTPUT_FOLDER_ID}}

# ── Alerts (SMTP; Gmail app password works)
EMAIL_FROM=
EMAIL_APP_PASS=                # strip spaces from Gmail's "xxxx xxxx xxxx xxxx"
EMAIL_TO={{ALERT_EMAIL}}

# ── Optional
FFMPEG_BIN=                    # override ffmpeg path; default = bundled imageio-ffmpeg
REEL_FORCE=                    # NEVER set permanently — test switch only
```
`.gitignore` must cover `.env`, `.env.*`, `*service_account*.json`, `credentials*.json`,
state files, and the local render output dir. Add a pre-push secret scan for token
patterns (`sk-ant-`, `EAA…`, `1//…`, `ya29.`, `GOCSPX-`, `ghp_`, PEM headers).

---

## 8. Pitfalls — every one of these happened; build against them

1. **venv vs system Python.** Cron/manual runs outside the venv → `No module named
   'PIL'` / no ffmpeg → captions silently missing. Runner MUST `source venv/bin/activate`;
   optionally also `pip install Pillow imageio-ffmpeg` into system Python as a belt.
2. **Old system ffmpeg breaks the filters.** Ubuntu's ffmpeg 4.x ran the clip to the
   music's length (a 98-second reel!) and later failed the composite outright.
   Always prefer the bundled `imageio_ffmpeg.get_ffmpeg_exe()` (pinned v7+).
3. **Drive large-file interstitial.** `uc?export=download` returns an HTML scan
   warning for big files → corrupt "mp4" → `moov atom not found`. Use the
   `drive.usercontent.google.com/download?…&confirm=t` endpoint + form-submit
   fallback + HTML sanity check (§5.1).
4. **Any-format sources.** Auto-discovered clips arrive in any resolution/orientation;
   fragile filters (`scale2ref`) break on them. Always normalize to 1080×1920 first (§5.1).
5. **`invalid_grant` on a `1//` token** = the refresh token was minted with a
   DIFFERENT OAuth client than the one in `.env` (usually "Use your own OAuth
   credentials" was unchecked in the Playground). Client ID/secret and token must match.
6. **`ya29.` vs `1//`.** `ya29.` is a 1-hour access token; the refresh token starts
   with `1//`. Playground shows both — copy the right one.
7. **OAuth app in "Testing"** → refresh tokens die after 7 days. Publish to Production (§4.3).
8. **Graph scopes granted ≠ added.** Users can uncheck permissions in the consent
   popup; then `instagram_business_account` lookups fail with misleading errors.
   Verify via `GET /me/permissions`, and retry the lookup with the user token.
9. **Business-Portfolio pages don't appear in `/me/accounts`.** Use `FB_PAGE_ID`
   directly; fall back to `me/businesses → owned_pages`.
10. **No Instagram music via API.** `audio must be baked into the video file`; use
    license-free tracks (YouTube Audio Library, Pixabay, Mixkit).
11. **LLM output drift.** Models occasionally echo template markers (`<...>`),
    prepend `narrator:`/`me:` labels, or multi-line the caption. Strip/normalize in
    code (§5.4) — never trust prompt compliance alone.
12. **Switches are not counts.** `IG_AUTOPOST=3` means OFF, not "3 posts". Cadence
    comes from cron; per-slot state prevents double-posts.
13. **Never post the raw clip.** Enforce the `_raw.mp4` contract end-to-end.
14. **Secrets hygiene.** Never commit `.env` or key files; gitignore + a content-level
    secret scan before any git push. Assume any token pasted into a chat is leaked —
    rotate it.

---

## 9. Verification checklist (in the new project)

1. `python3 -c "import PIL, imageio_ffmpeg"` inside the venv → OK.
2. Drive token check (§4 snippet) → HTTP 200.
3. `list_folder_files({{CLIPS_FOLDER_ID}}, "video/")` → returns your clips.
4. Dry-run (`IG_AUTOPOST` unset): full run → log shows clip picked, music picked,
   `caption overlay burned`, Drive upload URL, "DRY-RUN would publish".
5. Extract a frame from the output (`ffmpeg -i out.mp4 -frames:v 1 f.png`) → overlay
   is present, readable, correctly placed; duration == `{{REEL_SECONDS}}`; file has
   an AAC audio stream.
6. Arm it (`IG_AUTOPOST=1`) → first real post appears on `{{IG_HANDLE}}`; state file
   records the slot; a re-run in the same slot skips.
7. Install the 3 cron lines; next day, verify 3 posts with different clips/captions,
   and that a clean day produced **zero** emails.
