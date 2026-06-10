---
name: proposal
description: Draft an Upwork/freelance proposal (cover letter + suggested rate) in John's voice, save it to ~/proposals as markdown ready to copy, and open it in VSCode
argument-hint: "<paste the job posting>"
allowed-tools: Bash, WebSearch
---

Draft a freelance proposal — a cover letter plus a suggested hourly rate — for the job posting in `$ARGUMENTS`, in John's voice. Then save and open it **with the script** (see **Save & open** — do NOT use the Write tool).

## Read John's resume FIRST (source of truth)

Before writing anything, extract his actual resume and treat it as the authoritative record of his experience:

```
pdftotext "$HOME/Downloads/John Pratt short ATS resume Jun 2026.pdf" -
```

Ground every experience claim in that resume — the roles, employers, technologies, and accomplishments it actually lists. Pull the specific, relevant bullets that map onto the job post; do not invent experience that isn't on it. If the `pdftotext` command fails (file moved/renamed), STOP and tell John rather than guessing his background.

## Who John actually is (anchor — the resume overrides this if they conflict)

- Senior **backend / data engineer**, ~10 YOE, Fortune 500 (Capital One, Lockheed).
- Bread and butter: **data pipelines** — reliable, scheduled, clean structured output.
- Has built **one** real large-scale Python scraper: Postgres work-queue, millions of records, scheduled runs, anti-bot handling. Genuine and worth leaning on — but it's one project, not a career specialty.

## Voice & honesty (NON-NEGOTIABLE)

- **Never overstate or fabricate.** Do NOT write things like "this is squarely what I do," "your exact niche," or anything implying he's a career specialist in something he isn't. Adjacent work is "in my wheelhouse" — not "my daily job." Never claim a project he hasn't done.
- **Translate his real experience onto the gig.** Map the pipelines/scraper/backend work onto what the post needs, and prove you read the post by hitting its *specific* requirements.
- **Direct, concrete, zero fluff.** No corporate-speak, no LinkedInese, no buzzwords. Write like a competent REAL person talking to another REAL person.
- **Write TO the prospect — but keep it human.** Address them directly — most of it in terms of "you," "your," and "we" — and frame the build as something you'd do together. Avoid abstract third-person framing that talks about "the work" / "a daily job" / "the project" in the air instead of to them.
  - ❌ "For a daily job, the things that matter are accuracy and reliability."
  - ✅ "For something you're running every day, what matters is that it stays correct — so we'd..."
  - Keep "I" light — a credential line and the odd "I'd build / I'll send" are fine; the outcome and the plan lean on you/we.
- **NOT salesy. It's a plain email between two competent people, not a pitch.** Banned: rhetorical sales questions ("So what does that get you?"), self-hype ("here's why you'd want me on it"), and landing-page lines ("you'll never be surprised by what you owe," "skip the usual headaches"). Say what you'd do, plainly — if a sentence sounds like marketing copy, flatten it or cut it.
- **Don't explain how the technology works — the client is buying an outcome, not a lecture.** State that you can do the thing; do NOT teach them the mechanics of it. Cut parentheticals and asides that describe *how* a tool/pattern works ("idempotent webhook handling, retries, reconciliation," "load balancing and auto-scaling to keep it scalable," "Terraform for reproducible infra," "a thin styling layer over React"). They already know what they asked for. Name the tech, claim the capability, move on — every clause should be about *what you'll deliver for them*, not a tutorial on the stack.
- Trust signals only where they fit: US-based, same-day communication, and a **not-to-exceed hour cap** for price-sensitive clients.

## Open & close (fixed shape)

- **Open with a light, genuine hook** — one short line showing the post caught your interest, *before* any capability talk. E.g. "This project looks like an interesting one," "Your posting made me curious," "This one caught my eye." Natural, not flattery — then go straight into the relevant experience.
- **Close with this CTA, every time:** *"Would love to hop on a quick call sometime to see how I can hopefully `<be an asset / help out>`."* Choose the trailing phrase to **mirror the client's own register and niche** from the post:
  - **"be an asset"** — corporate / finance / bank / enterprise / formal-sounding posts.
  - **"help out"** — casual / small-biz / startup / indie / friendly posts.
  - If they use their own verb ("support," "contribute," "lend a hand"), echo it instead. The line should sound like *them*, not boilerplate.

## Rate

1. `WebSearch` the current market rate for THIS task type in 2026 (e.g. "Upwork/Fiverr <task> hourly rate 2026") so the number is grounded in real data, not a guess.
2. Place him:
   - **No Upwork reviews on this profile yet** → can't command a premium; price to land the first contracts and bank reviews.
   - **Floor ~$40/hr.** Never bottom-feed against overseas $15–25 bids — he wins on US-based / senior / communication, not on price. Below ~$40 undercuts that positioning; pricing too high with zero reviews loses the gig.
   - Nudge within ~$35–50 on the client's price signals ("value," "intermediate," "worldwide").
3. State the number + ONE line of reasoning citing the market data.

## Save & open

`~/Documents` is macOS-TCC-protected and VSCode can't read files there — it errors with "NoPermissions" no matter who created the file. So proposals go in `~/proposals` (not protected), which VSCode opens fine. Don't use the Write tool either; just pipe the finished markdown to the script, which writes it there and opens it:

```
python3 ~/.agents/skills/proposal/scripts/draft_proposal.py "<short-title>" <<'EOF'
## Rate

<number + one-line reasoning>

## Cover Letter

<the body as a clean block, ready to copy/paste verbatim>
EOF
```

The script writes to `~/proposals/proposal-<slug>-<YYYY-MM-DD>.md`, opens it in VSCode, and prints the path — relay that path to John.
