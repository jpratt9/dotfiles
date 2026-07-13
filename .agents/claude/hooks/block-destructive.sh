#!/bin/bash
# PreToolUse guard: block destructive deletes (files + DB) unless explicitly allowed.
#
# Fires before every Bash tool call (even in bypass/auto mode). If the command
# matches a destructive pattern, exit 2 -> Claude Code blocks the call and shows
# the stderr message. Otherwise exit 0 -> normal flow.
#
# NOTE: command-string matching is a best-effort early guard, not OS-level
# enforcement; the model could route around it (perl unlink, python os.remove).
# It exists to stop the obvious cases (rm, find -delete, DELETE FROM, DROP).

input=$(cat)

# /allowdelete bypass: when the guard has been switched off (via the /allowdelete
# skill), allow everything. State lives in a file because env vars don't survive
# across separate tool calls. File contains "off" => guard disabled.
if [ "$(cat "/Users/john/.claude/hooks/.delguard" 2>/dev/null)" = "off" ]; then
  exit 0
fi

cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')
[ -z "$cmd" ] && exit 0

# Lowercase copy for case-insensitive SQL keyword checks.
lc=$(printf '%s' "$cmd" | tr '[:upper:]' '[:lower:]')

block() {
  echo "BLOCKED by delete-guard hook: $1" >&2
  echo "This command was auto-blocked because it deletes files or database rows." >&2
  echo "If you (the user) actually want this, tell Claude explicitly and it can be run." >&2
  exit 2
}

# --- file deletion ---
# Match the delete commands only as STANDALONE tokens, not substrings, so words
# like crm/charm/perform/confirm/warm/firmware don't false-positive. A token
# counts when it's preceded by line-start or a shell separator (space ; | & ( `)
# and followed by whitespace or line-end. Also matches an absolute path form
# (/bin/rm, /usr/bin/rmdir). grep -E is used because bash `case` globs have no
# word boundaries. `terraform` is stripped first (it contains "rm" but is safe).
scan="${cmd//terraform/}"
_word_del='(^|[[:space:];|&(`])(/[[:alnum:]/_.-]*/)?(rm|rmdir|unlink|shred|trash)([[:space:]]|$)'
if printf '%s' "$scan" | grep -Eq "$_word_del"; then
  # figure out which one for the message
  for w in rm rmdir unlink shred trash; do
    if printf '%s' "$scan" | grep -Eq "(^|[[:space:];|&(\`])(/[[:alnum:]/_.-]*/)?${w}([[:space:]]|\$)"; then
      block "$w (file removal)"
    fi
  done
  block "file removal"
fi
# find/rsync --delete flag (distinct from the rm-family word check above)
case "$cmd" in
  *"-delete"*)                             block "-delete (find/rsync file deletion)";;
esac

# git history / worktree destroyers
case "$cmd" in
  *"git clean"*)                           block "git clean";;
  *"git reset --hard"*)                    block "git reset --hard";;
esac

# indirect deletes via interpreters
case "$lc" in
  *"unlink("*|*"os.remove"*|*"os.unlink"*|*"shutil.rmtree"*|*"rmtree("*) \
                                           block "indirect file delete (perl/python)";;
esac

# --- database destruction (case-insensitive) ---
case "$lc" in
  *"delete from"*)                         block "SQL DELETE FROM";;
  *"drop table"*)                          block "SQL DROP TABLE";;
  *"drop database"*)                       block "SQL DROP DATABASE";;
  *"truncate "*)                           block "SQL TRUNCATE";;
esac

exit 0
