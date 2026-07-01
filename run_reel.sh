#!/bin/bash
# Velluto Instagram reel — one post for the CURRENT time-slot (morning/noon/evening).
# Scheduled 3×/day via cron, decoupled from the daily SEO pipeline (run.sh).
# instagram_reel_brief.py self-gates to one post per slot per day, so an accidental
# double-fire won't double-post. Uses the pip-bundled ffmpeg (no apt needed).
cd /root/velluto/velluto-seo-bot || exit 1

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] reel: $*"; }

# Pick up the latest code without fighting the SEO pipeline's commits.
git pull --rebase --autostash origin main >/dev/null 2>&1 \
  || { git rebase --abort 2>/dev/null; log "git pull failed — running on local code"; }

source venv/bin/activate
log "starting reel run"
python3 instagram_reel_brief.py || log "reel run failed"
deactivate 2>/dev/null
log "done"
