---
name: backup
description: Back up dotfiles + ~/.agents tree by running ~/dev/dotfiles/backup.sh with a context-aware commit message
disable-model-invocation: false
---

Run the dotfiles backup wrapper:

```
python3 ~/.agents/skills/backup/backup.py "<commit message>"
```

Pick a commit message that reflects what actually changed in this session — e.g. "add backup skill", "tweak CLAUDE.md auto-commit rule", "add no-tests-during-audit rule". Keep it short, lowercase, no conventional-commit prefix (the backup script handles its own format).

If nothing meaningful changed and the user just wants a routine backup, pass no argument and the script defaults to `automatic backup <timestamp>`.
