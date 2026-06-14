---
name: thinking
description: Toggle extended Thinking on/off by setting alwaysThinkingEnabled in settings.json. Usage: /thinking on | /thinking off
disable-model-invocation: false
---

Toggle the user's extended Thinking. The arg is `on` or `off`.

Run the deterministic script (it edits `~/.claude/settings.json` through its
symlink, atomically, with stdlib only):

```
python3 ~/.claude/skills/thinking/scripts/toggle_thinking.py <arg>
```

- `<arg>` = `on` → `alwaysThinkingEnabled: true`
- `<arg>` = `off` → `alwaysThinkingEnabled: false`
- no/invalid arg → the script prints the current value + usage and exits 2

Report the script's output to the user, then tell them: the change applies on the
next session (the running CLI may need a `/config` reload or restart). For an
immediate launch-time hard-off, they can instead `export MAX_THINKING_TOKENS=0`
before running `claude` (zeroes the reasoning budget so the model replies at once).
