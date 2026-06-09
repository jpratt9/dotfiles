#!/usr/bin/env python3
"""Write a proposal draft (markdown read from stdin) to ~/proposals and open it
in VSCode.

The drafting (cover letter + rate) is done by the model; this script only does
the file I/O + open. Files go in ~/proposals, NOT ~/Documents: ~/Documents is a
macOS-TCC-protected folder that VSCode can't read (it errors "NoPermissions"),
no matter the file's owner or permissions. ~/proposals isn't protected, so
VSCode opens it fine.

Usage:
    python3 draft_proposal.py "<title or slug>"   # markdown body on stdin
"""
import datetime
import re
import subprocess
import sys
from pathlib import Path


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "proposal"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: draft_proposal.py <title-or-slug>  (markdown body on stdin)",
              file=sys.stderr)
        return 2

    slug = slugify(sys.argv[1])
    body = sys.stdin.read()
    if not body.strip():
        print("error: no markdown body on stdin", file=sys.stderr)
        return 2

    date = datetime.date.today().isoformat()
    out_dir = Path.home() / "proposals"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"proposal-{slug}-{date}.md"

    # Remove any stale copy first so this is a clean file.
    try:
        out.unlink()
    except FileNotFoundError:
        pass

    out.write_text(body)
    out.chmod(0o644)
    print(f"wrote {out}")

    try:
        subprocess.run(["code", str(out)], check=True)
        print("opened in VSCode")
    except FileNotFoundError:
        print("note: 'code' CLI not on PATH — open the file manually", file=sys.stderr)
    except subprocess.CalledProcessError as exc:
        print(f"note: 'code' failed to open the file: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
