#!/bin/bash
# Velluto SEO bot — daily pipeline.
# Hardened: no single step aborts the chain, persistence (commit+push) ALWAYS
# runs, and every step is logged with a timestamp (cron appends to /var/log/seo-bot.log).
# Note: intentionally no `set -e` — one failing step must not kill the rest.
cd /root/velluto/velluto-seo-bot || exit 1

FAILED=()
log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
step() { local msg="$1"; shift; log "▶ $msg"; if "$@"; then return 0; else log "✗ step failed (continuing): $msg"; FAILED+=("$msg"); return 0; fi; }

log "[SEO Bot] Starting"

# Sync latest code first. --rebase --autostash tolerates leftover local changes;
# on any failure we abort a half-done rebase and continue on local code.
git pull --rebase --autostash origin main \
  || { git rebase --abort 2>/dev/null; log "✗ git pull failed — running on local code"; }

source venv/bin/activate

# Shopify (current auth): mint a fresh ~24h Admin API token from client_id+secret
# and export it so every downstream script inherits a valid token. No static token.
export SHOPIFY_TOKEN="$(python3 mint_shopify_token.py 2>>/var/log/seo-bot.log)"
if [ -n "$SHOPIFY_TOKEN" ]; then
  log "✓ Shopify token minted (${SHOPIFY_TOKEN:0:6}…)"
else
  log "✗ Shopify token mint failed — check SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET in .env"
  FAILED+=("Shopify token mint failed")
fi

step "generate + publish article"  python3 seo_bot.py
step "backlinks + sitemap ping"    python3 link_builder.py
# Pinterest paused: posting needs boards:write, which Pinterest only grants with
# Standard access (app-review + demo video) — a poor fit for a headless single-
# account bot. Re-enable by uncommenting once Standard access is approved.
# step "pinterest"                   python3 pinterest_poster.py
step "seo optimizer"               python3 seo_optimizer.py
step "geo monitor"                 python3 geo_monitor.py
step "dashboard"                   python3 dashboard.py

# NOTE: the Instagram reel is posted 3×/day on its OWN schedule via run_reel.sh
# (morning/noon/evening cron), decoupled from this once-daily SEO pipeline.

# 28-day blog review + site SEO/GEO audit. Self-gates to every 28 days, so a
# daily invocation is harmless (exits early when not due). Ensure Chromium for
# the Playwright vision-UI step (idempotent; quick no-op once installed).
python3 -c "import playwright" 2>/dev/null && playwright install --with-deps chromium >/dev/null 2>&1 || true
step "blog review (28d gate)"      python3 blog_review.py

# ── Persistence: always commit + push; never abort the run ──────────────────
git config user.name  "vps-bot"
git config user.email "leopold@velluto-brand.com"
git add -A

# ── SAFETY NET: never let a secret reach the public repo (see .env.save leak) ─
# Layer 1: drop secret/backup files from the staged set even if .gitignore misses one.
BAD_FILES=$(git diff --cached --name-only \
  | grep -iE '(^|/)\.env([._]|$)|\.(save|bak|orig|swp|swo|pem|key|p12)$|(^|/)id_rsa|(^|/)(credentials|service_account|gdrive_sa|token).*\.json|_sa\.json$' || true)
if [ -n "$BAD_FILES" ]; then
  log "⚠️ SECURITY: unstaging secret-like file(s): $(echo "$BAD_FILES" | tr '\n' ' ')"
  echo "$BAD_FILES" | xargs -r git reset -q HEAD --
  echo "$BAD_FILES" | xargs -r rm -f
fi
# Layer 2: scan staged CONTENT for secret tokens; if found, ABORT commit+push.
SECRET_BLOCK=false
if git diff --cached 2>/dev/null | grep -qE 'sk-ant-[A-Za-z0-9_-]{16}|sk-[A-Za-z0-9]{20}|ghp_[A-Za-z0-9]{20}|github_pat_[A-Za-z0-9_]{20}|AIza[A-Za-z0-9_-]{30}|xox[baprs]-[A-Za-z0-9-]{10}|GOCSPX-[A-Za-z0-9_-]{20}|1//[A-Za-z0-9_-]{30}|ya29\.[A-Za-z0-9_-]{30}|EAA[A-Za-z0-9]{40}|hf[-_][A-Za-z0-9-]{20}|-----BEGIN[A-Z ]*PRIVATE KEY-----'; then
  log "✗ SECURITY: secret-looking token in staged content — commit & push SKIPPED. Inspect 'git diff --cached'."
  SECRET_BLOCK=true
  FAILED+=("SECURITY: secret token blocked from push")
fi

if [ "$SECRET_BLOCK" = true ]; then
  : # leave changes uncommitted; the daily report flags this as ACTION NEEDED
elif git diff --cached --quiet; then
  log "nothing to commit"
else
  git commit -m "chore: daily update $(date -u +%Y-%m-%d)" && log "committed daily update"
fi

# Push with a few retries; tolerate failure so the run still ends cleanly.
PUSH_OK=true
if [ "$SECRET_BLOCK" = true ]; then
  PUSH_OK=false
else
  for i in 1 2 3; do
    if git push origin main; then log "✓ pushed to origin/main"; break; fi
    if [ "$i" = 3 ]; then
      log "✗ git push still failing after 3 tries — commits remain local (check auth)"; PUSH_OK=false
    else
      log "push attempt $i failed; retrying in $((i * 5))s"; sleep $((i * 5))
    fi
  done
fi

# ── Resource watchdog: warn early (email) if a key/quota needs topping up/renewing.
# Silent when everything is healthy; throttled so it won't spam the same warning daily.
log "▶ resource monitor"
python3 resource_monitor.py || log "✗ resource monitor failed"

# ── Daily email report (always) — summary + ⚠️ alert if anything needs action ─
export RUN_FAILED=$(printf '%s\n' "${FAILED[@]}")
export RUN_PUSH_OK="$PUSH_OK"
log "▶ daily email report"
python3 daily_report.py || log "✗ daily report failed"

log "[SEO Bot] Done"
