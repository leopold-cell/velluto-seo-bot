#!/bin/bash
# Velluto Instagram engagement bot — one session per invocation.
# Scheduled 3×/day via cron (mirrors the old /root/velluto/instagram/run.sh).
#
# Session number is derived from the hour unless passed as $1:
#   morning  (before 12:00) → session 1
#   midday   (12:00–17:59)  → session 2
#   evening  (18:00+)       → session 3
# Session 3 is the one that sends the daily summary email (see bot.py).
#
# A lockfile prevents two sessions overlapping (a slow session must never run
# into the next slot — that would look like a bot to Instagram).
set -u

BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$BOT_DIR/.." && pwd)"
LOCK="/tmp/velluto_ig_bot.lock"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ig: $*"; }

# ── Session detection ──
if [ "${1:-}" = "--session" ] && [ -n "${2:-}" ]; then
  SESSION="$2"
elif [ -n "${1:-}" ] && [ "${1#--}" = "$1" ]; then
  SESSION="$1"                      # bare number, e.g. run_ig.sh 2
else
  H=$(date '+%-H')
  if   [ "$H" -lt 12 ]; then SESSION=1
  elif [ "$H" -lt 18 ]; then SESSION=2
  else                       SESSION=3
  fi
fi

# Pass any remaining flags (e.g. --dry-run) straight through to the bot.
EXTRA=()
for a in "$@"; do
  case "$a" in
    --session|"$SESSION") ;;         # already consumed
    *) EXTRA+=("$a") ;;
  esac
done

# ── Lockfile (flock if available, mkdir fallback) ──
run_bot() {
  cd "$BOT_DIR" || { log "cannot cd to $BOT_DIR"; exit 1; }

  # Pick up latest code without fighting the SEO pipeline's commits.
  ( cd "$REPO_DIR" && git pull --rebase --autostash origin main >/dev/null 2>&1 \
      || { git rebase --abort 2>/dev/null; log "git pull failed — running on local code"; } )

  # venv lives at the repo root (shared with the SEO pipeline).
  if [ -f "$REPO_DIR/venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$REPO_DIR/venv/bin/activate"
  fi

  log "starting session $SESSION ${EXTRA[*]:-}"
  python3 -u bot.py --session "$SESSION" "${EXTRA[@]:-}" || log "session $SESSION failed"
  deactivate 2>/dev/null
  log "done"
}

if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK"
  if ! flock -n 9; then
    log "another session is running (lock $LOCK held) — skipping"
    exit 0
  fi
  run_bot
else
  if ! mkdir "$LOCK.d" 2>/dev/null; then
    log "another session is running (lock $LOCK.d held) — skipping"
    exit 0
  fi
  trap 'rmdir "$LOCK.d" 2>/dev/null' EXIT
  run_bot
fi
