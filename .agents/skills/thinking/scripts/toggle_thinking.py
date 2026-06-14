#!/usr/bin/env python3
"""Toggle extended Thinking by setting alwaysThinkingEnabled in settings.json.

Usage: toggle_thinking.py [on|off]
  on  -> alwaysThinkingEnabled = true
  off -> alwaysThinkingEnabled = false
  (no arg / anything else) -> print current value + usage, exit 2

Edits ~/.claude/settings.json (a symlink). Writes through the symlink via a
temp-file-then-replace-contents so a crash can't truncate the real file and the
symlink itself is preserved. Pure stdlib, no jq.
"""
import json
import os
import sys
import tempfile

SETTINGS = os.path.expanduser("~/.claude/settings.json")


def main(argv):
    arg = (argv[1].strip().lower() if len(argv) > 1 else "")

    with open(SETTINGS, "r") as f:
        cfg = json.load(f)

    if arg not in ("on", "off"):
        cur = cfg.get("alwaysThinkingEnabled", "<unset>")
        print(f"alwaysThinkingEnabled is currently: {cur}")
        print("Usage: /thinking on | /thinking off")
        return 2

    cfg["alwaysThinkingEnabled"] = (arg == "on")

    # Render first, then replace the symlink target's CONTENTS (not the link):
    # write a sibling temp file, then copy its bytes over the resolved real path.
    text = json.dumps(cfg, indent=2) + "\n"
    real = os.path.realpath(SETTINGS)
    d = os.path.dirname(real)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".settings.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, real)  # atomic; real is the link target, so link stays valid
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    print(f"alwaysThinkingEnabled = {cfg['alwaysThinkingEnabled']}  (wrote {SETTINGS})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
