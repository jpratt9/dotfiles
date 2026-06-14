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

# Single source of truth: ~/.agents holds all skills + per-tool config
# (CLAUDE.md, settings.json, GEMINI.md), symlinked into ~/.claude and ~/.gemini.
# Back up the whole tree. -L resolves any symlinks to their real contents.
mkdir -p "$DOTFILES_DIR/.agents"
rsync -aL --delete ~/.agents/ "$DOTFILES_DIR/.agents/"

# Claude per-tool config now lives under ~/dev/.agents/.claude (symlinked into
# ~/.claude); back it into the repo's .agents/claude. -L resolves symlinks.
mkdir -p "$DOTFILES_DIR/.agents/claude"
rsync -aL --delete ~/dev/.agents/.claude/ "$DOTFILES_DIR/.agents/claude/"

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
