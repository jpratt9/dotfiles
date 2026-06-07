#!/usr/bin/env python3
"""Thin wrapper around ~/dev/dotfiles/backup.sh.

Usage:
    python3 backup.py "commit message"
    python3 backup.py            # uses backup.sh's default "automatic backup <ts>"
"""
import subprocess
import sys

BACKUP_SCRIPT = "/Users/john/dev/dotfiles/backup.sh"


def main() -> int:
    args = [BACKUP_SCRIPT]
    if len(sys.argv) > 1:
        args.append(sys.argv[1])
    return subprocess.run(args).returncode


if __name__ == "__main__":
    sys.exit(main())
