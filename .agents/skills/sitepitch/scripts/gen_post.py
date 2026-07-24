#!/usr/bin/env python3
"""Generate variations of a website-build outreach post for a given profession
and copy one to the macOS clipboard, ready to paste into a group post or DM.

Premade templates — close variations of the same short post, not freestyle. The
profession is injected (and pluralized: "roofer" -> "2 roofers"), the page count
is picked at random from 10/15/20 each run, and the call-to-action is picked at
random per post — so repeated runs hand you a slightly different post, handy for
posting across groups without tripping duplicate-content spam filters.

Usage:
  python3 gen_post.py "roofer"
  python3 gen_post.py "gutter cleaner" --count 4 --pick 3
  python3 gen_post.py "junk removal pro" --slots 3
  python3 gen_post.py "landscaper" --pages 15 --no-copy

Prints the variations numbered and copies one (the first, or --pick N) to the
clipboard via pbcopy. Exit codes: 0 = ok; 2 = bad usage.
"""
import argparse
import random
import subprocess
import sys

# Premade templates: tight variations of the original post. Same voice/structure,
# small swaps only. Slots:
#   {trade} - profession, already pluralized ("roofers", "gutter cleaners")
#   {slots} - how many you're taking on this month
#   {pages} - site size in pages (randomly 10/15/20 unless --pages is given)
#   {cta}   - call-to-action, picked at random per post from CTAS
TEMPLATES = [
    "Looking to build a free website for {slots} {trade} this month. {pages} page site, you can host it anywhere. {cta}",
    "Building free websites for {slots} {trade} this month. {pages} page site, host it wherever you want. {cta}",
    "Looking to make a free {pages} page website for {slots} {trade} this month. Host it anywhere you like. {cta}",
    "Free website for {slots} {trade} this month. {pages} page site, you can host it anywhere. {cta}",
    "Looking to build a free website for {slots} {trade} this month. Full {pages} page site, host it wherever. {cta}",
]

# Call-to-action lines, picked at random per post.
CTAS = [
    "Let me know!",
    "Hit me up!",
    "Let's talk!",
    "First come first serve!",
    "Who's in?",
    "Let me know! \U0001F447",
]

# Site sizes to pick from at random each run.
PAGE_CHOICES = (10, 15, 20)


def pluralize(word):
    """Naive pluralize for trade nouns: roofer -> roofers, junk removal pro ->
    junk removal pros, company -> companies. Leaves an already-plural word alone."""
    w = word.strip()
    if not w or w.endswith("s"):
        return w
    if w.endswith("y") and w[-2:-1].lower() not in "aeiou":
        return w[:-1] + "ies"
    return w + "s"


def copy_to_clipboard(text):
    """Copy text to the macOS clipboard via pbcopy (a system tool, no deps).
    Returns True on success, False if pbcopy is missing or errors."""
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        print(f"[warn] couldn't copy to clipboard: {e}", file=sys.stderr)
        return False


def build_posts(trade, templates, ctas, slots, pages, count, rng):
    """Fill `count` shuffled templates with the trade/slots/pages and a random
    CTA per post, and return them."""
    pool = list(templates)
    rng.shuffle(pool)
    count = max(1, min(count, len(pool)))
    return [t.format(trade=trade, slots=slots, pages=pages, cta=rng.choice(ctas))
            for t in pool[:count]]


def main():
    ap = argparse.ArgumentParser(
        description="Generate website-build outreach posts for a profession and copy one to the clipboard.")
    ap.add_argument("profession", help='trade, e.g. "roofer", "gutter cleaner", "junk removal pro" (auto-pluralized)')
    ap.add_argument("--count", type=int, default=5, help="how many variations to show (default 5, max 5)")
    ap.add_argument("--pick", type=int, default=1, help="which shown variation to copy (1-based, default 1)")
    ap.add_argument("--slots", default="2", help='spots you\'re offering this month (default "2")')
    ap.add_argument("--pages", type=int, default=None,
                    help="force a site size; default picks randomly from 10/15/20")
    ap.add_argument("--seed", type=int, default=None, help="RNG seed for reproducible output")
    ap.add_argument("--no-copy", action="store_true", help="just print; don't touch the clipboard")
    args = ap.parse_args()

    if not args.profession.strip():
        ap.error("profession must not be empty")

    rng = random.Random(args.seed)
    trade = pluralize(args.profession)
    pages = args.pages if args.pages is not None else rng.choice(PAGE_CHOICES)
    posts = build_posts(trade, TEMPLATES, CTAS, args.slots, pages, args.count, rng)
    pick = args.pick if 1 <= args.pick <= len(posts) else 1

    for i, post in enumerate(posts, 1):
        marker = "   ← copied" if (not args.no_copy and i == pick) else ""
        print(f"{i}. {post}{marker}")

    if not args.no_copy and copy_to_clipboard(posts[pick - 1]):
        print(f"\n✓ Variation {pick} copied to the clipboard — ready to paste.")


if __name__ == "__main__":
    main()
