#!/bin/bash
# Daily dotfiles backup script

DOTFILES_DIR="$HOME/dev/dotfiles"
LOG_FILE="$DOTFILES_DIR/backup.log"

# Optional custom commit message ($1); defaults to the automatic-backup format
COMMIT_MSG="${1:-automatic backup $(date '+%Y-%m-%d %H:%M')}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

cd "$DOTFILES_DIR" || exit 1

# Pull latest
git pull --rebase

# Copy dotfiles
cp ~/.zshrc "$DOTFILES_DIR/.zshrc"
cp ~/.zprofile "$DOTFILES_DIR/.zprofile"
cp -r ~/.git-hooks "$DOTFILES_DIR/.git-hooks"
mkdir -p "$DOTFILES_DIR/.claude"
cp ~/.claude/settings.json "$DOTFILES_DIR/.claude/settings.json"
cp ~/.claude/CLAUDE.md "$DOTFILES_DIR/.claude/CLAUDE.md"
# ~/.gitignore_global excludes .claude/, so force-add this backup copy
git add -f "$DOTFILES_DIR/.claude"

# Skills now live in the shared ~/.agents source-of-truth dir (symlinked from
# ~/.claude/skills, ~/.gemini/skills, ~/.gemini/antigravity/skills)
mkdir -p "$DOTFILES_DIR/.agents"
rsync -a --delete ~/.agents/skills/ "$DOTFILES_DIR/.agents/skills/"

# Gemini CLI memory file only (NOT the whole ~/.gemini — it holds oauth creds)
mkdir -p "$DOTFILES_DIR/.gemini"
cp ~/.gemini/GEMINI.md "$DOTFILES_DIR/.gemini/GEMINI.md"

# Check for changes
if [ -z "$(git status -s)" ]; then
    log "No changes to backup"
    exit 0
fi

# Commit and push
git add -A
git commit -m "$COMMIT_MSG"
if git push; then
    log "Backup successful"
else
    log "ERROR: Push failed"
    exit 1
fi
