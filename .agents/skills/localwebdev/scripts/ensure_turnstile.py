#!/usr/bin/env python3
"""Idempotently add Cloudflare Turnstile to a built client site.

Guarantees, per site, that:
  1. every page carrying a <form> (and contact.html regardless) loads the
     Turnstile api.js script,
  2. every <form> contains a .cf-turnstile widget div,
  3. the stylesheet carries the .turnstile-box rule.

Nothing is touched when it is already there, so this is safe to run on every
deploy.

Parsing is done by real parsers -- BeautifulSoup for HTML, tinycss2 for CSS --
never by pattern-matching markup. But the documents are NOT reserialized: a full
BeautifulSoup round-trip rewrites attribute order, self-closes void elements and
eats blank lines (measured: 425-947 changed lines on an untouched page). So the
parser is used to *find* the insertion offsets (Tag.sourceline / .sourcepos) and
only those offsets are spliced. Every other byte of the file is preserved.

Usage:
  python3 ensure_turnstile.py --dir <site dir> [--sitekey KEY] [--css PATH]
                              [--theme dark|light|auto] [--check]

Exit: 0 ok (prints JSON summary), 2 no sitekey configured (warns, no changes),
      3 bad usage, 4 missing dependency / unparseable input,
      5 --check found something missing.
"""
import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_SRC = "https://challenges.cloudflare.com/turnstile/v0/api.js"
SCRIPT_TAG = f'<script src="{SCRIPT_SRC}" async defer></script>'
WIDGET_CLASS = "cf-turnstile"
CSS_SELECTOR = ".turnstile-box"
CSS_BLOCK = """
/* Cloudflare Turnstile widget (injected by ensure_turnstile.py) */
.turnstile-box { margin-bottom: 1.25rem; min-height: 65px; }
"""
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("missing dependency: beautifulsoup4 (pip install beautifulsoup4)", file=sys.stderr)
    sys.exit(4)

try:
    import tinycss2
except ImportError:
    tinycss2 = None


def env_sitekey():
    if not ENV_PATH.exists():
        return None
    for line in ENV_PATH.read_text().splitlines():
        if line.strip().startswith("TURNSTILE_SITEKEY="):
            return line.partition("=")[2].strip() or None
    return None


def line_offsets(text):
    """Absolute char offset of the start of each 1-based line."""
    offs, pos = [0], 0
    for line in text.split("\n")[:-1]:
        pos += len(line) + 1
        offs.append(pos)
    return offs


def abs_offset(offs, tag):
    """(sourceline, sourcepos) -> absolute offset. None when unavailable."""
    if tag is None or tag.sourceline is None or tag.sourcepos is None:
        return None
    idx = tag.sourceline - 1
    if idx >= len(offs):
        return None
    return offs[idx] + tag.sourcepos


def insert_point(text, idx):
    """Where to splice a block so it reads as its own line above `idx`.

    Returns (offset, own_line). When only whitespace precedes the anchor on its
    line, insert at the line start and let the snippet carry its own indent --
    that leaves the anchor's indentation untouched. When the anchor shares a
    line with other markup (minified or single-line HTML) insert at the anchor
    itself and emit a compact one-liner, so nothing on that line is displaced.
    """
    ls = text.rfind("\n", 0, idx) + 1
    return (ls, True) if text[ls:idx].strip() == "" else (idx, False)


def widget_markup(sitekey, theme, indent, own_line=True):
    attrs = f'class="{WIDGET_CLASS} turnstile-box" data-sitekey="{sitekey}" data-theme="{theme}"'
    if not own_line:
        return f"<div {attrs}></div>"
    pad = " " * indent
    return (
        f'{pad}<!-- Cloudflare Turnstile - supplies the cf-turnstile-response field. -->\n'
        f'{pad}<div class="{WIDGET_CLASS} turnstile-box"\n'
        f'{pad}     data-sitekey="{sitekey}"\n'
        f'{pad}     data-theme="{theme}"></div>\n\n'
    )


def has_turnstile_script(soup):
    return any(SCRIPT_SRC in (s.get("src") or "") for s in soup.find_all("script"))


def form_widget(form):
    """The .cf-turnstile element already inside this form, if any."""
    for el in form.find_all(True):
        if WIDGET_CLASS in (el.get("class") or []):
            return el
    return None


def plan_html(path, sitekey, theme):
    """Return (list_of_(offset, text)_inserts, notes) for one HTML file."""
    text = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(text, "html.parser")
    offs = line_offsets(text)
    inserts, notes = [], []

    forms = soup.find_all("form")

    # --- widget div, once per form ------------------------------------------
    for form in forms:
        existing = form_widget(form)
        if existing is not None:
            key = existing.get("data-sitekey")
            if key and sitekey and key != sitekey:
                notes.append(f"widget present with a different sitekey ({key}) - left as-is")
            continue

        # anchor on the submit control so the widget sits directly above it
        anchor = form.find("button", attrs={"type": "submit"}) or form.find(
            "input", attrs={"type": "submit"})
        anchor_at = abs_offset(offs, anchor)
        indent = anchor.sourcepos if anchor is not None and anchor.sourcepos else 0

        if anchor_at is None:
            # no submit control -> place it just before the form's closing tag
            fstart = abs_offset(offs, form)
            close = text.lower().find("</form>", fstart if fstart is not None else 0)
            if close == -1:
                notes.append("form with no submit control and no </form> - skipped")
                continue
            anchor_at, indent = close, (form.sourcepos or 0) + 2

        at, own_line = insert_point(text, anchor_at)
        inserts.append((at, widget_markup(sitekey, theme, indent, own_line)))

    # --- api.js script -------------------------------------------------------
    wants_script = bool(forms) or path.name.lower() == "contact.html"
    if wants_script and not has_turnstile_script(soup):
        head = soup.find("head")
        if head is None:
            notes.append("no <head> - script not added")
        else:
            hstart = abs_offset(offs, head) or 0
            close = text.lower().find("</head>", hstart)
            if close != -1:
                # sit on its own line immediately above </head>
                indent = " " * (len(text[:close]) - len(text[:close].rstrip(" ")))
                inserts.append((close, f"{SCRIPT_TAG}\n{indent}"))
            else:
                gt = text.find(">", hstart)
                if gt == -1:
                    notes.append("malformed <head> - script not added")
                else:
                    inserts.append((gt + 1, f"\n{SCRIPT_TAG}"))

    return inserts, notes


def apply_inserts(path, inserts):
    text = path.read_text(encoding="utf-8")
    for at, snippet in sorted(inserts, key=lambda p: p[0], reverse=True):
        text = text[:at] + snippet + text[at:]
    path.write_text(text, encoding="utf-8")


def css_has_rule(css_text):
    """True when CSS_SELECTOR is a real selector (not just text in a comment)."""
    if tinycss2 is None:
        # conservative fallback: strip comments, then look for the selector
        return CSS_SELECTOR in re.sub(r"/\*.*?\*/", "", css_text, flags=re.S)

    def scan(rules):
        for rule in rules:
            if rule.type == "qualified-rule":
                if CSS_SELECTOR in tinycss2.serialize(rule.prelude):
                    return True
            elif rule.type == "at-rule" and rule.content:
                if scan(tinycss2.parse_blocks_contents(rule.content,
                                                       skip_comments=True,
                                                       skip_whitespace=True)):
                    return True
        return False

    return scan(tinycss2.parse_stylesheet(css_text, skip_comments=True, skip_whitespace=True))


def main():
    ap = argparse.ArgumentParser(description="Ensure Cloudflare Turnstile is wired into a built site.")
    ap.add_argument("--dir", required=True, help="site directory to scan for .html files")
    ap.add_argument("--sitekey", help="Turnstile sitekey (default: TURNSTILE_SITEKEY from skill .env)")
    ap.add_argument("--css", help="stylesheet to ensure the rule in (default: <dir>/styles.css)")
    ap.add_argument("--theme", default="dark", choices=["dark", "light", "auto"])
    ap.add_argument("--check", action="store_true", help="report only; change nothing")
    args = ap.parse_args()

    root = Path(args.dir).expanduser()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        sys.exit(3)

    sitekey = args.sitekey or env_sitekey()
    if not sitekey:
        print("[turnstile] no TURNSTILE_SITEKEY in skill .env and none passed - skipping",
              file=sys.stderr)
        sys.exit(2)

    changed, notes = {}, []
    for path in sorted(root.rglob("*.html")):
        try:
            inserts, file_notes = plan_html(path, sitekey, args.theme)
        except Exception as exc:  # unparseable file should not silently pass
            print(f"failed to process {path}: {exc}", file=sys.stderr)
            sys.exit(4)
        notes += [f"{path.name}: {n}" for n in file_notes]
        if inserts:
            changed[str(path.relative_to(root))] = len(inserts)
            if not args.check:
                apply_inserts(path, inserts)

    css_path = Path(args.css).expanduser() if args.css else root / "styles.css"
    css_added = False
    if css_path.is_file():
        css_text = css_path.read_text(encoding="utf-8")
        if not css_has_rule(css_text):
            css_added = True
            if not args.check:
                css_path.write_text(css_text.rstrip("\n") + "\n" + CSS_BLOCK, encoding="utf-8")
    else:
        notes.append(f"stylesheet not found: {css_path}")

    result = {
        "sitekey": sitekey,
        "theme": args.theme,
        "html_files_changed": changed,
        "css_rule_added": css_added,
        "css_parser": "tinycss2" if tinycss2 else "fallback",
        "notes": notes,
        "mode": "check" if args.check else "apply",
    }
    print(json.dumps(result, indent=1))

    if args.check and (changed or css_added):
        sys.exit(5)


if __name__ == "__main__":
    main()
