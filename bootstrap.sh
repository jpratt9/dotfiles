#!/bin/bash
#
# Bootstrap a brand-new Mac to John's setup.
#
# On a fresh machine, run:
#   bash <(curl -fsSL https://raw.githubusercontent.com/jpratt9/dotfiles/main/bootstrap.sh)
#
# Idempotent — safe to re-run. Each step skips itself if already done.

set -euo pipefail

DOTFILES_DIR="$HOME/dev/dotfiles"
REPO_URL="https://github.com/jpratt9/dotfiles.git"

say() { printf "\n\033[1;34m==> %s\033[0m\n" "$*"; }


# 1. Xcode Command Line Tools (Git, compilers — needed before Homebrew).
if ! xcode-select -p >/dev/null 2>&1; then
  say "Installing Xcode Command Line Tools (a system dialog will pop up)..."
  xcode-select --install
  # Block until the user finishes the GUI installer.
  until xcode-select -p >/dev/null 2>&1; do sleep 5; done
fi


# 2. Homebrew (the official installer auto-detects Apple Silicon vs Intel and
#    picks /opt/homebrew vs /usr/local).
if ! command -v brew >/dev/null 2>&1; then
  say "Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  # Make brew available in THIS shell on Apple Silicon (where it isn't on PATH
  # by default until the next login).
  if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi
fi


# 3. Clone the dotfiles repo (if this script wasn't already run from inside it).
if [ ! -d "$DOTFILES_DIR" ]; then
  say "Cloning dotfiles into $DOTFILES_DIR..."
  mkdir -p "$(dirname "$DOTFILES_DIR")"
  git clone "$REPO_URL" "$DOTFILES_DIR"
fi
cd "$DOTFILES_DIR"


# 4. Install everything in the Brewfile (CLI tools, casks, vscode extensions,
#    go tools, npm globals). Idempotent — only installs what's missing.
say "Running brew bundle install..."
brew bundle install --file="$DOTFILES_DIR/Brewfile"


# 5. Symlink dotfiles into $HOME. -s symlink, -f overwrite existing, -n don't
#    descend into a target that's already a symlinked directory.
say "Symlinking shell + git config into \$HOME..."
ln -sfn "$DOTFILES_DIR/.zshrc"    "$HOME/.zshrc"
ln -sfn "$DOTFILES_DIR/.zprofile" "$HOME/.zprofile"
ln -sfn "$DOTFILES_DIR/.bashrc"   "$HOME/.bashrc"


# 6. Optional macOS system defaults (only if the script exists in the repo).
if [ -f "$DOTFILES_DIR/macos-defaults.sh" ]; then
  say "Applying macOS system defaults..."
  bash "$DOTFILES_DIR/macos-defaults.sh"
fi


say "Bootstrap complete. Open a new terminal to pick up the new shell config."
