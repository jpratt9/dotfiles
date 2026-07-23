---
name: sitepitch
description: Generate variations of a website-build outreach post for a given profession and copy one to the clipboard
argument-hint: "<profession> (e.g. roofer, gutter cleaner, junk removal pro)"
allowed-tools: Bash
---

Generate a ready-to-paste website-build outreach post for a profession and copy
one to the clipboard. Uses a fixed set of premade templates (close variations of
the same short post — not freestyle). The profession is injected and pluralized
("roofer" → "2 roofers"), the page count is picked at random from 10/15/20 each
run, and the call-to-action is picked at random per post — so repeated runs give
a slightly different post, useful for posting across groups without tripping
duplicate-content spam filters.

## Steps

1. Run the generator with the profession the user gave, as a single quoted
   argument (singular is fine — it gets pluralized):

   ```
   python3 ~/.claude/skills/sitepitch/scripts/gen_post.py "<profession>"
   ```

   It prints the variations numbered and copies the first to the macOS clipboard
   (via pbcopy).

2. Show the user the variations and note which one landed on the clipboard
   (it's ready to paste).

3. Adjust on request with flags:
   - `--pick N` — copy variation N instead of the first
   - `--count N` — show more/fewer variations (default 5, max 5)
   - `--slots N` — spots offered this month (default 2)
   - `--pages N` — force a specific site size (default: random 10/15/20)
   - `--no-copy` — just print, leave the clipboard alone

The templates live in `scripts/gen_post.py` (the `TEMPLATES` list) — edit that
list to add/remove/reword posts.
