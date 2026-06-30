#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Machine-wide secret-leak guard. Run ONCE per machine/user:
#     bash scripts/setup_secret_guard.sh
#
# Protects EVERY git repo for this user (not just this project) with two layers:
#   1. a global .gitignore so .env / *.save / keys are never tracked anywhere
#   2. a global pre-commit hook that BLOCKS any commit containing a secret file
#      or a secret-looking token — including automated commits (e.g. cron).
# Idempotent and non-destructive: appends to existing config, chains to any
# repo-local pre-commit hook. Bypass intentionally (rare) with: git commit --no-verify
# ─────────────────────────────────────────────────────────────────────────────
set -e

GITIGNORE_GLOBAL="$HOME/.gitignore_global"
HOOKS_DIR="$HOME/.git-hooks"
MARK="# >>> velluto secret-guard >>>"

echo "🔒 Installing machine-wide secret guard for user '$(whoami)'…"

# ── Layer 1: global gitignore ────────────────────────────────────────────────
touch "$GITIGNORE_GLOBAL"
if ! grep -qF "$MARK" "$GITIGNORE_GLOBAL"; then
  cat >> "$GITIGNORE_GLOBAL" <<EOF
$MARK
# Secrets & credentials — never track in ANY repo
.env
.env.*
*.env
.envrc
*.pem
*.key
id_rsa
id_ed25519
*_rsa
credentials*.json
service-account*.json
*secret*.json
*.tfvars
# Editor / OS backups that can capture secrets
*.save
*.bak
*.orig
*.swp
*.swo
*~
.DS_Store
# <<< velluto secret-guard <<<
EOF
  echo "   • appended secret patterns to $GITIGNORE_GLOBAL"
else
  echo "   • $GITIGNORE_GLOBAL already has the secret-guard block"
fi
git config --global core.excludesFile "$GITIGNORE_GLOBAL"

# ── Layer 2: global pre-commit hook ──────────────────────────────────────────
mkdir -p "$HOOKS_DIR"
cat > "$HOOKS_DIR/pre-commit" <<'HOOK'
#!/bin/bash
# Machine-wide secret guard (installed by velluto setup_secret_guard.sh).
fail=0

# a) secret / backup files newly added to the commit
bad_files=$(git diff --cached --name-only --diff-filter=AM 2>/dev/null \
  | grep -iE '(^|/)\.env([._]|$)|\.(save|bak|orig|swp|swo|pem|key)$|(^|/)id_(rsa|ed25519)|credentials.*\.json|service-account.*\.json' || true)
if [ -n "$bad_files" ]; then
  echo "🚫 pre-commit: refusing to commit secret/backup file(s):"
  echo "$bad_files" | sed 's/^/     - /'
  fail=1
fi

# b) secret-looking tokens inside the staged diff
if git diff --cached 2>/dev/null | grep -qE \
  'sk-ant-[A-Za-z0-9_-]{16}|sk-[A-Za-z0-9]{20}|ghp_[A-Za-z0-9]{20}|gho_[A-Za-z0-9]{20}|github_pat_[A-Za-z0-9_]{20}|AIza[A-Za-z0-9_-]{30}|shpat_[a-f0-9]{32}|shpss_[a-f0-9]{32}|xox[baprs]-[A-Za-z0-9-]{10}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----'; then
  echo "🚫 pre-commit: a secret-looking token is in your staged changes — commit blocked."
  echo "     Inspect with:  git diff --cached"
  fail=1
fi

if [ "$fail" = 1 ]; then
  echo "     (False positive? bypass once with:  git commit --no-verify)"
  exit 1
fi

# Preserve any repo-local pre-commit hook (chain to it)
GITDIR="$(git rev-parse --git-common-dir 2>/dev/null)"
if [ -n "$GITDIR" ] && [ -x "$GITDIR/hooks/pre-commit" ]; then
  exec "$GITDIR/hooks/pre-commit" "$@"
fi
exit 0
HOOK
chmod +x "$HOOKS_DIR/pre-commit"
git config --global core.hooksPath "$HOOKS_DIR"

echo "   • installed pre-commit hook at $HOOKS_DIR/pre-commit"
echo
echo "✅ Done. Every git repo for this user now blocks secret files & tokens at commit time."
echo "   global gitignore : $(git config --global core.excludesFile)"
echo "   global hooksPath : $(git config --global core.hooksPath)"
echo "   Run this same script on any other machine you develop on."
