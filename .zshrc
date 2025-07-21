# export PYENV_ROOT="$HOME/.pyenv"
# [[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"
# eval "$(pyenv init -)"

export PATH="/usr/local/opt/python/libexec/bin:$PATH"

export TCL_LIBRARY="/usr/local/Cellar/tcl-tk/8.6.14/lib/tcl8.6"
export TK_LIBRARY="/usr/local/Cellar/tcl-tk/8.6.14/lib/tk8.6"
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion

export PATH="/usr/local/opt/python/libexec/bin:$PATH"
alias python="python3"
alias pip="pip3"

gp() {
    if [ -z "$1" ]; then
        echo "Error: Commit message required"
        return 1
    fi
    git add . &&
    git commit -am "$1" &&
    git push
}

gc() {
    if [ -z "$1" ]; then
        echo "Error: Branch name required"
        return 1
    fi
    git checkout "$1"
}

gs() {
    git status
}

caf() {
    caffeinate -u -s -i -d
}

voice_memos() {
    cd ~/Library/Group\ Containers/group.com.apple.VoiceMemos.shared
}

co() {
    if [ -n "$1" ]; then
        code "$1"
        return
    fi
    code .
}

zshrc() {
    code ~/.zshrc
}

execz() {
    exec zsh
}

# Created by `pipx` on 2025-02-04 15:42:04
export PATH="$PATH:/Users/john/.local/bin"

# Tailscale alias
alias tailscale="/Applications/Tailscale.app/Contents/MacOS/Tailscale"

export PATH="$HOME/.pyenv/bin:$PATH"
eval "$(pyenv init --path)"
eval "$(pyenv init -)"

nvm use v20.17.0