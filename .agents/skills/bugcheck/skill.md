---
name: bugcheck
description: Search the current repo for existing bug investigations, post-mortems, and documented issues related to a problem you're encountering
disable-model-invocation: false
---

Search the CURRENT REPO ONLY for any prior documentation, investigations, or code comments related to the bug or issue described by the user. Do NOT search the web. Do NOT search external repos.

## Steps

1. **Parse the issue** — Identify the key symptoms, error messages, file names, and technical terms from the user's description.

2. **Search repo docs** — Use Grep and Glob to search for matches in:
   - Documentation files (`**/*.md`, `**/*.txt`, `**/*.rst`, `**/*.adoc`, `**/*.doc`, `**/*.pdf`, `**/*.org`)
   - Post-mortems, READMEs, changelogs, known issues files
   - Code comments matching the symptoms
   - Git commit messages (`git log --all --oneline --grep="<keyword>"`)
   - Test files that reference the issue
   - Any files named `KNOWN_ISSUES`, `BUGS`, `CHANGELOG`, `TODO`, or similar

3. **Search code for related fixes** — Grep for:
   - Error messages or error codes mentioned
   - Function/variable names involved
   - Config values or flags that look like workarounds
   - Comments containing "fix", "hack", "workaround", "bug", "issue", "broken"

4. **Search conversation history (fallback only)** — If nothing found in the repo, search `.claude/projects/*/` JSONL files for prior conversations about this issue. Use grep on the JSONL files for keywords.

5. **Report findings** — For each match found:
   - File path and line number
   - The relevant content
   - Whether the issue was resolved and how
   - If no matches found anywhere, say so explicitly

## Rules
- ONLY search the current repo and conversation history. NEVER use WebSearch, WebFetch, or search external repos.
- Search broadly — use multiple keyword variations (e.g. "audio" AND "sound" AND "crackling" AND "distort")
- Read any matching files fully to understand context, don't just show the grep hit
- If you find a post-mortem or bug doc, summarize the root cause and resolution status
