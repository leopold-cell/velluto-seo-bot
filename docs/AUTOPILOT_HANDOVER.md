# Shopify Access Handover — Velluto Autopilot

This document describes everything the Autopilot repo needs in order to take
over Shopify access from `velluto-seo-bot`. It covers how access works today,
where the credentials live, the exact API surface in use, and the steps to
wire it all up on the Autopilot side.

## 1. How this bot accesses Shopify

There is no SDK, app framework, or OAuth flow. Every script calls the Shopify
**Admin API** directly with `requests`, authenticated by a single custom-app
access token sent as the `X-Shopify-Access-Token` header.

Three environment variables control everything:

| Variable | Purpose | Default |
|---|---|---|
| `SHOPIFY_TOKEN` | Admin API access token (custom app) | — (required) |
| `SHOPIFY_STORE` | Store domain | `velluto-brand.myshopify.com` |
| `BLOG_ID` | Numeric ID of the blog articles are published to | — (required by blog scripts) |

Any process that has these three variables has the same Shopify access this
bot has. That is the entire handover surface.

## 2. Where the token currently lives

The token exists in two places:

1. **VPS** — production runs via cron (`run.sh`) from
   `/root/velluto/velluto-seo-bot/`, which loads a `.env` file in the repo
   root. This is the only place the token is *readable* — copy it from there.
2. **GitHub Actions secrets** on `leopold-cell/velluto-seo-bot`
   (`SHOPIFY_TOKEN`, `SHOPIFY_STORE`, `BLOG_ID`), used by the
   `daily-blog.yml` and `meta-optimizer.yml` workflows. GitHub secrets are
   write-only and cannot be read back out.

If the VPS `.env` is ever lost, the token cannot be recovered (Shopify shows
custom-app tokens only once) — a new token must be generated in
Shopify admin → Settings → Apps and sales channels → Develop apps.

## 3. API surface in use (what the token must be able to do)

All calls target `https://{SHOPIFY_STORE}/admin/api/2024-01/...` unless noted.

### REST
| Endpoint | Methods | Used by |
|---|---|---|
| `products.json` | GET | `seo_bot.py`, `meta_optimizer.py` |
| `blogs/{BLOG_ID}/articles.json` (+ per-article) | GET, POST, PUT | `seo_bot.py`, `seo_optimizer.py`, `retrofit_translations.py`, `dashboard.py`, `scripts/fix_internal_links.py`, `scripts/strip_fences.py`, `decision/content_inventory.py` |
| `pages.json` | GET | `meta_optimizer.py` |
| `{resource}/{id}/metafields.json`, `metafields/{id}.json` | GET, POST, PUT | `meta_optimizer.py` (SEO meta descriptions on products, pages, articles) |
| `smart_collections.json`, `custom_collections.json` | GET | `decision/content_inventory.py` |
| `themes/{theme_id}/assets.json` | PUT | `scripts/deploy_theme.py` (CSS, Liquid section, article template) |

### GraphQL (`graphql.json`)
- Product queries (`seo_bot.py`, `meta_optimizer.py`)
- `translationsRegister` mutation for NL/EN article translations
  (`seo_bot.py`, `retrofit_translations.py`)
- `commercial_config.py` uses API version `2025-01`

### Required access scopes
A token reused or regenerated for Autopilot needs at minimum:

- `read_products`, `write_products` (product reads + product metafields)
- `read_content`, `write_content` (blog articles, pages, their metafields)
- `read_translations`, `write_translations` and `read_locales` (translationsRegister)
- `read_themes`, `write_themes` (only if Autopilot will also deploy theme assets)

## 4. Steps to grant Autopilot access

1. Copy the values of `SHOPIFY_TOKEN`, `SHOPIFY_STORE`, and `BLOG_ID` from
   `/root/velluto/velluto-seo-bot/.env` on the VPS.
2. In the Autopilot repo, add them as GitHub Actions secrets (Settings →
   Secrets and variables → Actions), and/or to its runtime `.env` if it runs
   on a server.
3. In Autopilot's code or workflows, expose them as environment variables
   under the same names and send the token as the
   `X-Shopify-Access-Token` header.
4. Verify with a read-only smoke call before going live:
   ```bash
   curl -s -H "X-Shopify-Access-Token: $SHOPIFY_TOKEN" \
     "https://$SHOPIFY_STORE/admin/api/2024-01/shop.json"
   ```

## 5. Caveats

- **Shared token = shared blast radius.** Both repos will act as the same
  Shopify app; rate limits are shared, and rotating the token breaks both at
  once. When convenient, create a dedicated custom app for Autopilot in
  Shopify admin with only the scopes above.
- **API version `2024-01` is past Shopify's 12-month support window.**
  Requests are currently auto-forwarded to the oldest supported version, but
  Autopilot should pin a current version rather than inheriting `2024-01`.
- **Decommissioning:** once Autopilot is live, disable the VPS cron entry for
  `run.sh` and the `workflow_dispatch` workflows here to avoid both systems
  publishing to the same blog.
