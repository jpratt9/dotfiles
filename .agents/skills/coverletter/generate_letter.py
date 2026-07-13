#!/usr/bin/env python3
"""Write a cover letter (piped in on stdin) to a timestamped file on the Desktop
and open it in VS Code.

Usage:
    python3 generate_letter.py < letter.txt
    ... | python3 generate_letter.py

Output: ~/Desktop/cover_letter_<YYYY-MM-DD_HHMMSS>.txt
Standard library only -- no dependencies.
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def _unwrap(text: str) -> str:
    """Collapse hard line breaks inside each block to a single line, keeping the
    blank lines between blocks. Compose the letter with a blank line between every
    part (greeting, each paragraph, closing, name) so this stays WYSIWYG."""
    blocks = text.strip().split("\n\n")
    return "\n\n".join(" ".join(b.split()) for b in blocks)


def main() -> None:
    text = sys.stdin.read()
    if not text.strip():
        sys.exit("No letter text on stdin -- pipe the composed cover letter in.")
    text = _unwrap(text)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out = Path.home() / "Desktop" / f"cover_letter_{stamp}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text.rstrip() + "\n", encoding="utf-8")
    print(out)

    # Open the letter in VS Code (uses the `code` CLI on PATH).
    try:
        subprocess.run(["code", str(out)], check=False)
    except FileNotFoundError:
        print(
            "VS Code 'code' command not found on PATH -- open the file manually.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
