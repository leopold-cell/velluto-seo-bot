#!/bin/bash
set -e
cd /root/velluto/velluto-seo-bot
git pull origin main
source venv/bin/activate
echo "[SEO Bot] Starting: $(date)"
python3 seo_bot.py
python3 link_builder.py      || true
python3 seo_optimizer.py     || true
python3 dashboard.py         || true
git config user.name "vps-bot"
git config user.email "leopold@velluto-brand.com"
git add -A
git diff --cached --quiet || git commit -m "chore: daily update $(date -u +%Y-%m-%d)"
git push
echo "[SEO Bot] Done: $(date)"
