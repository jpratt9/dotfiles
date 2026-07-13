---
name: coverletter
description: Write a targeted cover letter for John Pratt from a pasted job description, grounded in his real resume + case studies + certs, and save it to a timestamped .txt on the Desktop (opens in VS Code). Use when the user runs "/coverletter" (usually with a job description pasted in) or asks for a cover letter for a specific role.
---

# /coverletter

Writes a **targeted cover letter** for John Pratt — aimed at a specific job description and grounded in his real experience — then saves it to the Desktop as `cover_letter_<datetime>.txt` and opens it in VS Code.

## Input
The **job description**, pasted in as the skill's arguments (after the command). **If no JD was provided, ask the user to paste it and stop** — the whole point is to target the letter.

## Sources (in this skill's directory, `~/.claude/skills/coverletter/`)
- **`resume.pdf`** — job history / quantified accomplishments, skills, education. **Read it in full.**
- **`case-studies.md`** — his major projects (Rainmaker, Wraith, Content Machine, TALOS, UnitWolf, Eagle Eye).
- **`certs.md`** — 38 professional certifications.

## Steps
1. **Get the JD** from the arguments. No JD → ask for it and stop.
2. **Read the three sources** in the skill dir.
3. **Parse the JD:** company, role/title, the top 3–6 requirements / must-haves, the tech stack it emphasizes, and the tone/seniority. Grab a contact name if one is given (for the greeting).
4. **Compose the cover letter** — map John's *real, quantified* wins (from the resume + case studies) onto what this JD is actually asking for. Structure:
   - **Greeting** — use a name if given, else `Dear [Company] Hiring Team,`.
   - **Opening** — a specific hook connecting John to *this* role/company. Never "I am writing to apply for…".
   - **Body (1–2 paragraphs)** — match his strongest quantified accomplishments to the JD's key requirements (pull the real numbers: dollars saved, % gains, scale). Explicitly name the JD's tech that he's certified/experienced in.
   - **Close** — short, confident call to action.
   - **Sign-off** — `Sincerely,` then `John Pratt`.
   - **~250–400 words.** Every claim grounded in the sources — never invent experience or numbers.
   - **Formatting:** put a **blank line between every part** (greeting, each paragraph, closing, name), and write each paragraph as **one line** (no manual mid-paragraph breaks).
5. **Write it out:**
   ```bash
   python3 ~/.claude/skills/coverletter/generate_letter.py <<'TXT'
   <the cover letter you composed>
   TXT
   ```
6. **Report the output path** the script prints.

## Style
- Specific and **results-first** — lead with quantified impact matched to the JD. No fluff, no "I am passionate about."
- Confident, not arrogant; match the JD's tone and seniority.
- **First person** (it's his letter).

## Notes
- Output: `~/Desktop/cover_letter_<YYYY-MM-DD_HHMMSS>.txt`
- To refresh source material: drop a newer `resume.pdf` in, or edit the `.md` files.
