---
name: allowdelete
description: Toggle the local delete-guard hook (block-destructive.sh) off — or back on — so rm / find -delete / git reset --hard / DROP / DELETE FROM / TRUNCATE run without being blocked
argument-hint: "[on|off|status]"
allowed-tools: Bash
disable-model-invocation: true
---

Toggle the delete-guard PreToolUse hook (`~/.claude/hooks/block-destructive.sh`)
via its state file `~/.claude/hooks/.delguard`. The hook allows everything when
that file contains the literal text `off`; any other content (or a missing file)
keeps the guard active.

Read `$ARGUMENTS`, default to `on` when empty, and do EXACTLY ONE of the following:

- **`on` / empty / `allow` / `disable` / `off-guard`** — turn the guard OFF (allow deletes):
  ```
  printf off > ~/.claude/hooks/.delguard
  ```
  Then tell the user, verbatim intent: "Delete-guard OFF — rm / find -delete /
  git reset --hard / DROP / DELETE FROM / TRUNCATE now run without being blocked.
  Re-enable anytime with `/allowdelete off`."

- **`off` / `block` / `enable` / `restore` / `on-guard`** — turn the guard back ON:
  ```
  printf on > ~/.claude/hooks/.delguard
  ```
  Then tell the user: "Delete-guard ON — destructive commands are blocked again."

- **`status`** — report current state:
  ```
  cat ~/.claude/hooks/.delguard 2>/dev/null || echo "(no state file — guard ON by default)"
  ```
  If it prints `off`, report the guard is OFF; otherwise report it is ON.

Notes:
- This only flips the guard's state file. Do NOT run any destructive command
  yourself as part of running this skill.
- The change persists across tool calls and sessions until toggled back.
