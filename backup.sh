#!/bin/bash
# Daily dotfiles backup script

DOTFILES_DIR="$HOME/dev/dotfiles"
LOG_FILE="$DOTFILES_DIR/backup.log"

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
rsync -a --delete ~/.claude/skills/ "$DOTFILES_DIR/claude-skills/"

# Check for changes
if git diff --quiet; then
    log "No changes to backup"
    exit 0
fi

# Commit and push
git add -A
git commit -m "automatic backup $(date '+%Y-%m-%d %H:%M')"
if git push; then
    log "Backup successful"
else
    log "ERROR: Push failed"
    exit 1
fi
