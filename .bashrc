# ~/.bashrc: executed by bash(1) for non-login shells.
# see /usr/share/doc/bash/examples/startup-files (in the package bash-doc)
# for examples

# If not running interactively, don't do anything
case $- in
    *i*) ;;
      *) return;;
esac

# don't put duplicate lines or lines starting with space in the history.
# See bash(1) for more options
HISTCONTROL=ignoreboth

# append to the history file, don't overwrite it
shopt -s histappend

# for setting history length see HISTSIZE and HISTFILESIZE in bash(1)
HISTSIZE=1000
HISTFILESIZE=2000

# check the window size after each command and, if necessary,
# update the values of LINES and COLUMNS.
shopt -s checkwinsize

# If set, the pattern "**" used in a pathname expansion context will
# match all files and zero or more directories and subdirectories.
#shopt -s globstar

# make less more friendly for non-text input files, see lesspipe(1)
[ -x /usr/bin/lesspipe ] && eval "$(SHELL=/bin/sh lesspipe)"

# set variable identifying the chroot you work in (used in the prompt below)
if [ -z "${debian_chroot:-}" ] && [ -r /etc/debian_chroot ]; then
    debian_chroot=$(cat /etc/debian_chroot)
fi

# set a fancy prompt (non-color, unless we know we "want" color)
case "$TERM" in
    xterm-color|*-256color) color_prompt=yes;;
esac

# uncomment for a colored prompt, if the terminal has the capability; turned
# off by default to not distract the user: the focus in a terminal window
# should be on the output of commands, not on the prompt
#force_color_prompt=yes

if [ -n "$force_color_prompt" ]; then
    if [ -x /usr/bin/tput ] && tput setaf 1 >&/dev/null; then
	# We have color support; assume it's compliant with Ecma-48
	# (ISO/IEC-6429). (Lack of such support is extremely rare, and such
	# a case would tend to support setf rather than setaf.)
	color_prompt=yes
    else
	color_prompt=
    fi
fi

if [ "$color_prompt" = yes ]; then
    PS1='${debian_chroot:+($debian_chroot)}\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '
else
    PS1='${debian_chroot:+($debian_chroot)}\u@\h:\w\$ '
fi
unset color_prompt force_color_prompt

# If this is an xterm set the title to user@host:dir
case "$TERM" in
xterm*|rxvt*)
    PS1="\[\e]0;${debian_chroot:+($debian_chroot)}\u@\h: \w\a\]$PS1"
    ;;
*)
    ;;
esac

# enable color support of ls and also add handy aliases
if [ -x /usr/bin/dircolors ]; then
    test -r ~/.dircolors && eval "$(dircolors -b ~/.dircolors)" || eval "$(dircolors -b)"
    alias ls='ls --color=auto'
    #alias dir='dir --color=auto'
    #alias vdir='vdir --color=auto'

    alias grep='grep --color=auto'
    alias fgrep='fgrep --color=auto'
    alias egrep='egrep --color=auto'
fi

# colored GCC warnings and errors
#export GCC_COLORS='error=01;31:warning=01;35:note=01;36:caret=01;32:locus=01:quote=01'

# some more ls aliases
alias ll='ls -alF'
alias la='ls -A'
alias l='ls -CF'

# Add an "alert" alias for long running commands.  Use like so:
#   sleep 10; alert
alias alert='notify-send --urgency=low -i "$([ $? = 0 ] && echo terminal || echo error)" "$(history|tail -n1|sed -e '\''s/^\s*[0-9]\+\s*//;s/[;&|]\s*alert$//'\'')"'

# Alias definitions.
# You may want to put all your additions into a separate file like
# ~/.bash_aliases, instead of adding them here directly.
# See /usr/share/doc/bash-doc/examples in the bash-doc package.

if [ -f ~/.bash_aliases ]; then
    . ~/.bash_aliases
fi

# enable programmable completion features (you don't need to enable
# this, if it's already enabled in /etc/bash.bashrc and /etc/profile
# sources /etc/bash.bashrc).
if ! shopt -oq posix; then
  if [ -f /usr/share/bash-completion/bash_completion ]; then
    . /usr/share/bash-completion/bash_completion
  elif [ -f /etc/bash_completion ]; then
    . /etc/bash_completion
  fi
fi

# Use nearest .venv/bin/python (walks up from $PWD), else fall back to python3.
# Aliased as both `python` and `python3` so calls to either go through the venv.
python() {
  local d="$PWD"
  while [ "$d" != "/" ]; do
    if [ -x "$d/.venv/bin/python" ]; then
      "$d/.venv/bin/python" "$@"
      return
    fi
    d="$(dirname "$d")"
  done
  command python3 "$@"
}
python3() { python "$@"; }
alias open="explorer.exe"
alias claude="claude --append-system-prompt \"Never run git commands without explicit permission. If you are told to 'plan' something, write your plan to a file first before proceeding with implementation. If you ignore any of the user's instructions, you have failed. Unless you are told otherwise, whenever you modify code, you MUST re-run existing unit tests + add new tests for your new code - and if any tests fail, keep fixing your code until they don't. Unless instructed otherwise, whenever you use an external python library, you must inspect the \'requirements.txt\' file(s) for the project + make sure they're listed there + run a \'pip install -r requirements.txt\' to make sure it's actually installed to the system.\""



export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion

pip() {
  local d="$PWD"
  while [ "$d" != "/" ]; do
    if [ -x "$d/.venv/bin/pip" ]; then
      "$d/.venv/bin/pip" "$@"
      return
    fi
    d="$(dirname "$d")"
  done
  # outside any project venv: fall back to system pip with PEP 668 override
  if [[ "$1" == "install" || "$1" == "i" ]]; then
    command pip install --break-system-packages "${@:2}"
  else
    command pip "$@"
  fi
}
pip3() { pip "$@"; }

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
tfapply() {
    terraform plan
    terraform apply -auto-approve
}

bashrc() {
    code ~/.bashrc
}

execb() {
    exec bash
}

export AWS_PROFILE=tf
export POSTGRES_PORT=5433

# always use latest nodejs
nvm use v24.9.0 > /dev/null
export PIP_BREAK_SYSTEM_PACKAGES=1

# make terminal title current folder name
export PS1="\[\e]0;\W\a\]${debian_chroot:+($debian_chroot)}\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ "

# Report current directory to terminal so new tabs open in same folder (WSL/Windows Terminal)
PROMPT_COMMAND=${PROMPT_COMMAND:+$PROMPT_COMMAND; }'printf "\e]9;9;%s\e\\" "$(wslpath -w "$PWD" 2>/dev/null || echo "$PWD")"'

cd ~/dev