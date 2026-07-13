---
name: coverletter
description: Compose John Pratt's professional summary from his real source material (resume + case studies + certs) and save it to a timestamped .txt on the Desktop, opening it in VS Code. Use when the user types "/coverletter" or asks to write / generate his professional summary or cover-letter summary.
---

# /coverletter

Composes a professional summary of John Pratt from his **real source material** — his resume, his case studies, and his certifications — then writes it to the Desktop as `professional_summary_<datetime>.txt` and opens it in VS Code.

## Sources (all in this skill's directory, `~/.claude/skills/coverletter/`)
- **`resume.pdf`** — job history / experience (with quantified accomplishments), skills, and education. **The primary source — read it in full.**
- **`case-studies.md`** — his major personal/client projects (Rainmaker, Wraith, Content Machine, TALOS, UnitWolf, Eagle Eye).
- **`certs.md`** — 38 professional certifications, grouped by provider.

_To refresh the sources: drop a newer resume export in as `resume.pdf`, or edit the `.md` files._

## Steps

1. **Read all three sources** in this skill's directory (`resume.pdf`, `case-studies.md`, `certs.md`).
2. **Compose the professional summary.**
   - **Default:** a tight 3–4 paragraph summary — who he is, his strongest **quantified** accomplishments (pull the real numbers from the resume — dollars saved, % gains, scale), the range of systems he's built, and his cloud/cert breadth.
   - **Tailored:** if the user names a target role, company, tone, length, or POV, aim the summary at that.
   - Ground every claim in the sources. Do not invent numbers or experience.
3. **Write it out** with the bundled Python script (it stamps the datetime filename, writes to `~/Desktop/`, and opens it in VS Code):
   ```bash
   python3 ~/.claude/skills/coverletter/generate_summary.py - <<'TXT'
   <the summary you composed>
   TXT
   ```
4. **Report the output path** the script prints.

## Style
- Confident, specific, **results-first** — lead with quantified impact (saved $X, cut Y%, scaled to Z).
- No fluff ("passionate about"), no generic filler.
- Default third person ("John Pratt is…"); first person only if the user asks.

## Notes
- Output file: `~/Desktop/professional_summary_<YYYY-MM-DD_HHMMSS>.txt`
- The script's built-in `SUMMARY` string is only a fallback for running it with no stdin; the real path is composing from the sources above and piping via `-`.
