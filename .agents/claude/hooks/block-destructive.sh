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
case "$cmd" in
  *"rm "*|*"rm -"*|*"/bin/rm"*)            block "rm (file removal)";;
  *"unlink "*)                             block "unlink";;
  *"rmdir "*)                              block "rmdir";;
  *"-delete"*)                             block "-delete (find/rsync file deletion)";;
  *"shred "*)                              block "shred";;
  *"trash "*)                              block "trash";;
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
