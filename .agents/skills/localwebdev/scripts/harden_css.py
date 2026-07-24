#!/usr/bin/env python3
"""Inject the defensive base into a built styles.css — deterministically, so it
can't be forgotten.

These four rules remove whole classes of mobile-overflow bug at the source
rather than leaving them to be caught downstream:

  min-width: 0        flex/grid children default to min-width:auto (min-content)
                      and REFUSE to shrink — the single most common cause of a
                      blown-out track.
  scroll-padding-top  keeps anchors and scrollIntoView clear of the sticky nav,
                      instead of landing under it.
  max-width: 100%     replaced elements never exceed their column.
  overflow-wrap       a long URL/email/phone number can't force a wide box.

It also STRIPS `overflow-x: hidden` off any `body` rule. That declaration hides
horizontal overflow instead of fixing it, masks real bugs, and makes a mobile
screenshot look clipped rather than scrollable. Scope containment to the element
that intentionally bleeds (`overflow-x: clip` on its section) instead.

The block is inserted EARLY — after any @charset/@import, which CSS requires to
come first — so ordinary author rules later in the file still override it.

Stdlib only. Idempotent: re-running is a no-op once the marker is present.

Usage:
  python3 harden_css.py --css ~/dev/<slug>/public/styles.css

Exit codes: 0 = injected or already present; 2 = the file was missing.
"""
import argparse
import re
import sys

MARKER = "defensive base — injected by harden_css.py"

BLOCK = """/* === {marker}; do not hand-edit === */
*, *::before, *::after {{ box-sizing: border-box; min-width: 0; }}
html {{ scroll-padding-top: calc(var(--nav-h, 72px) + 1rem); }}
img, svg, video, iframe, canvas, table {{ display: block; max-width: 100%; }}
p, li, h1, h2, h3, h4, blockquote, td, dd, dt {{ overflow-wrap: anywhere; }}
/* === end defensive base === */

""".format(marker=MARKER)

# @charset / @import must precede all other rules, so the block goes after them.
_PREAMBLE = re.compile(r"^\s*(?:@charset[^;]*;|@import[^;]*;|/\*.*?\*/|\s)*", re.S)

# any rule whose selector list mentions `body` as a whole word
_BODY_RULE = re.compile(r"(?P<sel>[^{}]*\bbody\b[^{}]*)\{(?P<body>[^{}]*)\}", re.I)
# the declaration may be last in the block, i.e. terminated by end-of-body
# rather than a semicolon (the braces are already stripped off by then).
_OVERFLOW_X_HIDDEN = re.compile(
    r"[^;{}]*\boverflow-x\s*:\s*hidden\s*(?:;|$)", re.I | re.M)


def log(msg):
    print(f"[harden-css] {msg}", file=sys.stderr)


def strip_body_overflow_x(css):
    """Remove `overflow-x: hidden` from every rule targeting body.
    Returns (new_css, count_removed)."""
    removed = [0]

    def fix(m):
        body, n = _OVERFLOW_X_HIDDEN.subn("", m.group("body"))
        removed[0] += n
        return f"{m.group('sel')}{{{body}}}"

    return _BODY_RULE.sub(fix, css), removed[0]


def harden(css):
    """Return (new_css, already_present, overflow_removed)."""
    stripped, removed = strip_body_overflow_x(css)
    if MARKER in css:
        return stripped, True, removed
    end = _PREAMBLE.match(stripped).end()
    return stripped[:end] + BLOCK + stripped[end:], False, removed


def main(argv=None):
    ap = argparse.ArgumentParser(description="Inject the defensive CSS base.")
    ap.add_argument("--css", required=True, help="path to the built styles.css")
    args = ap.parse_args(argv)

    try:
        with open(args.css, encoding="utf-8") as f:
            css = f.read()
    except OSError as e:
        log(f"cannot read the stylesheet: {e}")
        return 2

    new_css, already, removed = harden(css)
    if new_css != css:
        with open(args.css, "w", encoding="utf-8") as f:
            f.write(new_css)

    bits = []
    bits.append("defensive base already present" if already else "injected defensive base")
    if removed:
        bits.append(f"stripped `overflow-x: hidden` from {removed} body rule(s)")
    log("; ".join(bits) + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
