#!/usr/bin/env python3
"""Post-build LCP guard for localwebdev sites.

The scroll-reveal pattern these sites use hides elements at `opacity: 0` until
main.js adds an "in"/"visible" class via IntersectionObserver. Harmless below the
fold — but when that treatment lands on an ABOVE-THE-FOLD element (the hero, the
header), the LCP element can't paint until main.js has downloaded and run. On a
throttled phone that's a multi-second "element render delay" that wrecks the
mobile LCP (e.g. a 3s LCP that's ~2.9s of render delay, not image load).

This scans styles.css for the class(es) defined with `opacity: 0` AND a
transition/animation (i.e. entrance-animation "hidden" states), then strips those
classes off every element up to the end of the hero section so the first screen
paints immediately. Below-the-fold reveals are left untouched.

Stdlib only. Idempotent — safe to run on every build.

Usage:
  python3 lcp_guard.py --html public/index.html --css public/styles.css

Exit codes: 0 = ran (whether or not it changed anything); 2 = a file was missing.
"""
import argparse
import re
import sys


def log(msg):
    print(f"[lcp-guard] {msg}", file=sys.stderr)


def hidden_classes(css):
    """Class names the CSS parks at opacity:0 with a transition/animation — the
    "hidden until revealed" state of an entrance animation. Requiring the
    transition/animation avoids stripping statically-invisible decorations."""
    hide = set()
    # Match individual rule blocks. `[^{}]*` stops at the inner brace, so nested
    # @media wrappers don't fold their child rules into one match.
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        park = re.search(r"opacity\s*:\s*0(\.0+)?\s*(;|$)", body.strip())
        animates = re.search(r"\b(transition|animation)\b", body)
        if park and animates:
            hide.update(re.findall(r"\.([A-Za-z0-9_-]+)", sel))
    return hide


def hero_cutoff(html):
    """Index just past the hero section's </section> — the end of the first
    viewport. Prefers a <section> whose class mentions 'hero'; falls back to the
    first <section>. None if the page has no section to anchor on."""
    m = re.search(r"<section[^>]*class\s*=\s*[\"'][^\"']*hero[^\"']*[\"']", html, re.I)
    if not m:
        m = re.search(r"<section\b", html, re.I)
    if not m:
        return None
    close = re.search(r"</section\s*>", html[m.start():], re.I)
    return m.start() + close.end() if close else None


def strip_region(html, cutoff, hide):
    """Remove `hide` classes from every class="..." in html[:cutoff]. Returns
    (new_html, count_removed)."""
    removed = [0]

    def fix(m):
        quote, toks = m.group(1), m.group(2).split()
        kept = [t for t in toks if t not in hide]
        removed[0] += len(toks) - len(kept)
        return f"class={quote}{' '.join(kept)}{quote}"

    head = re.sub(r"class\s*=\s*([\"'])(.*?)\1", fix, html[:cutoff], flags=re.S)
    return head + html[cutoff:], removed[0]


def main():
    ap = argparse.ArgumentParser(description="Strip reveal classes off above-the-fold elements.")
    ap.add_argument("--html", required=True, help="path to the built index.html")
    ap.add_argument("--css", required=True, help="path to the built styles.css")
    args = ap.parse_args()

    try:
        css = open(args.css).read()
        html = open(args.html).read()
    except OSError as e:
        log(f"cannot read a build file: {e}")
        sys.exit(2)

    hide = hidden_classes(css)
    if not hide:
        log("no opacity:0 entrance-animation classes in the CSS — nothing to guard.")
        return
    cutoff = hero_cutoff(html)
    if cutoff is None:
        log("no <section> to locate the hero — skipping.")
        return

    new_html, n = strip_region(html, cutoff, hide)
    if n:
        with open(args.html, "w") as f:
            f.write(new_html)
        log(f"stripped {n} reveal-class instance(s) [{', '.join(sorted(hide))}] from the "
            f"above-the-fold region so the LCP element paints immediately.")
    else:
        log(f"above-the-fold region already clean [{', '.join(sorted(hide))}] — LCP-safe.")


if __name__ == "__main__":
    main()
