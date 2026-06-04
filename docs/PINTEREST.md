# Pinterest Auto-Posting

Autonomous daily Pinterest pinning for Velluto. Runs as part of the daily cron
(`run.sh`) right after `link_builder.py`, using the official **Pinterest API v5**.

Two pin types per run:

| Type        | Source                              | Image                         | Link            |
|-------------|-------------------------------------|-------------------------------|-----------------|
| **Article** | newest entries in `published_today.json` | `og:image` of the article page | article URL     |
| **Product** | Shopify catalogue, rotated by date  | Shopify product image         | product URL     |

Pin titles/descriptions are written by Claude Haiku (Pinterest-optimised,
keyword-rich). Already-posted article URLs / product handles are remembered in
`pinterest_log.json` and skipped for `dedupe_days` (default 90).

## 1. Credentials (`.env` on the VPS)

The target board is resolved by name (`config/pinterest.yml` → `boards.name`,
default `"Dolce Vita"`), so you only need the auth values.

**Recommended (stays autonomous):** Pinterest access tokens expire in ~30 days,
so provide the OAuth refresh trio. A fresh access token is then minted at the
start of every run (same pattern as the existing Google/GSC `GOOGLE_REFRESH_TOKEN`):

```ini
PINTEREST_APP_ID=...
PINTEREST_APP_SECRET=...
PINTEREST_REFRESH_TOKEN=...
```

**Simple (manual renewal):** a single static token. Works, but posting stops
when it expires (~30 days) until you replace it:

```ini
PINTEREST_ACCESS_TOKEN=pina_...
```

If both are present the refresh flow wins and the static token is used only as a
fallback when a refresh call fails.

Optionally pin numeric board IDs (these win over name resolution and save one API
call per run):

```ini
PINTEREST_BOARD_ID=1234567890             # one shared board…
# …or a board per pin type:
PINTEREST_ARTICLE_BOARD_ID=1234567890
PINTEREST_PRODUCT_BOARD_ID=0987654321
```

`ANTHROPIC_API_KEY` and `SHOPIFY_TOKEN`/`SHOPIFY_STORE` are already present for the
SEO bot and are reused.

### How to get the values
- **App ID / secret**: Pinterest Developer Portal → your approved app (`claude2`)
  → app settings.
- **Refresh token**: run the one-time OAuth flow with scopes `boards:read`,
  `pins:read`, `pins:write`, `user_accounts:read` (authorize the app → exchange
  the returned `code` at `POST /v5/oauth/token` for `access_token` +
  `refresh_token`). Store the `refresh_token`. (Trial access is enough to post to
  your own boards.)
- **Static access token** (simple path): generate one directly in the portal.
- **Board**: not needed if the name in `config/pinterest.yml` matches your board.
  To see all boards + their numeric IDs:
  ```bash
  python3 pinterest_poster.py --list-boards
  ```

## 2. Dependencies

No new packages — uses `requests`, `anthropic`, `PyYAML`, `python-dotenv`, all
already in `requirements.txt`.

## 3. Behaviour / tuning — `config/pinterest.yml`

```yaml
enabled: true
boards:
  name: "Dolce Vita"          # resolved to a board ID via the API at runtime
limits:
  article_pins_per_day: 2
  product_pins_per_day: 1
dedupe_days: 90
hashtags: ["#cycling", "#cyclingglasses", ...]
article_image_sources: [og_image]   # optionally: [og_image, higfields]
```

Set `enabled: false` to pause posting without touching the cron.

## 4. Running

```bash
python3 pinterest_poster.py            # post per config
python3 pinterest_poster.py --dry-run  # build pins + descriptions, do NOT post
```

It is already wired into `run.sh`:

```
python3 link_builder.py      || true
python3 pinterest_poster.py  || true   # ← here
python3 seo_optimizer.py     || true
```

If `PINTEREST_ACCESS_TOKEN` or a board ID is missing, the script logs a warning
and exits cleanly — safe to deploy before the token is in place.

## 5. Optional: Higfields.ai generated images

The autonomous VPS cron has **no MCP access**, so runtime image generation needs
a direct HTTP endpoint. To use Higfields-generated images for article pins:

```ini
HIGHFIELDS_API_KEY=...
HIGHFIELDS_API_URL=https://api.higfields.ai/...   # the image-generation endpoint
```

then add `higfields` to `article_image_sources` in `config/pinterest.yml`. The
integration is fail-safe: if generation fails it falls back to the article
`og:image`, so a run never breaks. (Response is parsed for `image_url` / `url` /
`data[0].url`; adjust `higfields_generate()` if the API returns a different shape.)

## 6. Logs

`pinterest_log.json` records every attempt per day with status (`posted` /
`error` / `dry_run` / `skipped`), pin ID, dedupe key and link — used both for
auditing and for cross-day de-duplication.
