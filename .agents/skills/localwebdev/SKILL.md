---
name: localwebdev
description: Take an existing local business (a URL + pasted text/Google reviews) and spin up a sleek 2026 semi-premium "revamp" static site for it, then deploy it to a brand-new Cloudflare Pages project with wrangler Direct Upload. Use when John says /localwebdev or wants to build+deploy a client demo site from a business URL.
argument-hint: "<business-url> — <notes, google reviews, or existing site copy>"
allowed-tools: Agent, Bash, Write, Edit, Read, WebFetch
---

Build a static "revamp site" for the business in `$ARGUMENTS` and deploy it to its own Cloudflare Pages project. This is John's client-demo pipeline — the goal is a live `<slug>.pages.dev` URL he can flip open on an iPad and use to close the client / justify higher rates. After deploy, record the business in John's CRM (§6).

`$ARGUMENTS` = a business URL followed by free-text context (Google reviews, existing site copy, notes). Parse the URL out; treat the rest as source material. If no URL is given, ask for one before proceeding.

## 0. Pick a project slug
Derive a short kebab-case slug from the business name (e.g. "Liliana's Hair Salon" → `hairbyliliana` or `lilianas-hair-salon`). This is the Cloudflare Pages project name AND the working dir name. It becomes `<slug>.pages.dev`. Keep it lowercase, alphanumeric + hyphens, ≤ 58 chars.

## 1. Analyze the real business FIRST (agent)
Spawn ONE agent (general-purpose) to extract the real brand + business facts. Do not guess or fabricate — a wrong phone number or fake price is worse than omitting it. Have it pull, with exact values and source URLs:
- **Logo** image URL(s); download them to the scratchpad and note colors/style.
- **Brand colors** (hex) and **fonts** from the live site's CSS/theme config.
- **Services & prices** — exact names + amounts. Many small businesses use Square/Fresha/Vagaro; the booking widget's JSON is the authoritative catalog (more reliable than scraping). If prices are "varies", say so.
- **Business info**: address, phone, email, hours, booking link, social links.
- **Copy/tagline** and any real **reviews** (with names) for social proof.
- **Booking system** + the direct public booking URL.
- **Google Maps place URL** for the business — needed for the default photo pull (§2a). Their reviews almost always come from Google Maps, so this is usually available; capture the listing/place URL if findable.

The browser extension is often not connected — that's fine; the agent should pull from the site HTML, embedded bootstrap/config JSON, and the booking platform's JSON API instead.

Wait for the agent, then work from its verified data. Copy the logo(s) into `public/assets/`.

## 2. Build the site (webdesign principles)
Create the working dir at `~/dev/<slug>/` with the site in `public/`:
```
public/index.html   public/styles.css   public/script.js   public/assets/<logos>
```
Follow the `webdesign` skill for craft. Positioning is **semi-premium** so they can charge more — elevate, don't just modernize. Concretely:
- **Keep their real logo.** Build the palette + type up from their actual brand (don't invent a new identity), but refine it (muted/elevated versions of their colors, a distinctive display + body font pairing — never Inter/Arial/Roboto).
- **Pull their real Google photos by default (§2a) and build a gallery from them.** Never invent or fake photos. Only when the photo pull yields nothing (no token, no Maps URL, or none returned) fall back to a type-led, photo-light layout — lean on typography, color, texture (CSS grain/gradient-mesh), and the real logo, leaving a clearly-commented gallery section ready for their Instagram shots.
- **Use real content only**: real services (bilingual if they are), real hours, real reviews (lightly trimmed for length is fine), real contact info, real booking link. Frame "price varies" services as a bespoke/consultation menu — that supports the premium tier.
- Single page, sections roughly: sticky nav + Book CTA → hero (bold statement, rating proof) → services menu → social proof/stats → real reviews → visit (hours/address/map/seal) → final CTA → footer. Booking buttons all point to their existing booking URL (no backend).
- **First viewport must be COMPLETE — nothing clipped.** Everything that logically belongs on the opening screen (headline, subcopy, both primary CTAs, the rating/proof line, and any hero side-card like a signature-item/price panel) must be fully visible within the initial viewport on BOTH desktop and mobile — never bleeding past the bottom edge (the #1 recurring failure: the star rating / proof line half-cut at the fold). To guarantee it:
  - Size the hero to the real viewport: `min-height: 100svh` and account for the sticky nav (e.g. `min-height: calc(100svh - var(--nav-h))`). Use `svh`/`dvh`, **never `vh`** — `vh` ignores mobile browser chrome and causes exactly this overflow.
  - Make the hero a flex column that fits its box (`justify-content: center`, controlled `gap`), and cap the display font + vertical rhythm with `clamp()` whose **max is tuned so the CTA row and proof line still clear the fold** — headlines shrink on short/mobile viewports rather than pushing content off-screen.
  - On mobile, if a hero side-card can't fit alongside everything, let it reflow below and shrink the headline so the core (headline + CTA + proof) still fits one screen; heavy secondary content may move just below the fold, but the primary CTA and proof never do.
  - **Verify before shipping:** check the rendered hero at 1440×900 (desktop) and 390×844 (mobile) and confirm the proof line and both CTAs are on-screen with no clipping; tighten the `clamp()` maxes/gaps until they are. Same discipline for any other section meant to read as a single screen.
- Responsive, reduced-motion safe, scroll-reveal, mobile menu that's actually hidden until toggled (default `display:none`, not just the `hidden` attr — a class `display:flex` overrides `[hidden]`).

No local dev server — it's self-contained (relative assets, CDN fonts). John opens `public/index.html` directly. See his preference on this.

## 2a. Google Business Profile photos (ON by default)
Pull the business's real Google photos **by default** on every run — do it whenever a **Google Maps place URL** is available (from §1) and the Apify token is set. Skip only if John explicitly says to leave photos out, there's no usable Maps URL, or the token isn't set. Cost is pennies per business (see below), so default to doing it.

Needs John's Apify token. It lives in his macOS Keychain via envchain (namespace `apify`, var `APIFY_TOKEN`) — run the script under `envchain apify` and the token is injected; never pass it on the command line. If `envchain --list` doesn't show `apify`, tell him to run `envchain --set apify APIFY_TOKEN` and skip this step for now — do NOT block the build on it.

Run the bundled script (stdlib only, no pip install):
```
envchain apify python3 <skill-dir>/scripts/fetch_gbp_photos.py \
  --url "<google maps place url>" \
  --out ~/dev/<slug>/public/assets/gallery \
  --max 12 --size s1600
```
It runs the Apify actor `solidcode~google-maps-photos-scraper` synchronously (run-sync-get-dataset-items), downloads up to `--max` images at web resolution into `public/assets/gallery/`, and writes `gallery.json` (file, category, owner, source, place). Cost is ~$0.50/1,000 images (a dozen photos is pennies). It exits non-zero if the token is missing (3) or the actor returns nothing (2/4) — handle gracefully and fall back to the photo-light layout.

Then build the gallery **from `gallery.json`** — render a responsive image grid in `index.html`, `loading="lazy"`, sized/cropped tastefully to match the design. Only render the gallery section if photos were actually downloaded. Pick the flattering, on-brand shots.

Note: these are public Google Maps photos — a mix of owner- and customer-posted (this actor doesn't reliably label which, so `--owner-only` is a no-op; skip it). That's fine for the client's own site. Just curate: use the good ones.

## 3. Wire up deploy tooling
In `~/dev/<slug>/` write `package.json`:
```json
{
  "name": "<slug>-site",
  "version": "1.0.0",
  "private": true,
  "scripts": { "deploy": "./deploy.sh" },
  "devDependencies": { "wrangler": "^4" }
}
```
Then generate the deploy script with the bundled generator — it writes an executable `deploy.sh` (wrangler Direct Upload, `PROJECT` set to the slug) into the project root:
```
python3 <skill-dir>/scripts/write_deploy_sh.py --project <slug> --name "<business name>" --dir ~/dev/<slug>
```
Then `npm install`. Deploy/redeploy is now one command — `./deploy.sh` (or `npm run deploy`); the client gets a self-contained project with no cloud console or IaC needed. Only `public/` ships — `package.json`, `node_modules`, `README.md`, `deploy.sh` never deploy. (Note: Cloudflare Pages serves `index.html` with a 200 for any unmatched path, so probing `/README.md` returns the homepage, not a leak — don't be alarmed by that.)

Write a short `README.md` (what it is, `./deploy.sh` to (re)deploy, the live URL, TODOs like optimize logo / self-host fonts / add Instagram gallery).

## 4. Deploy + verify
Static site → no Terraform / IaC. Create the Pages project once (idempotent — if it reports "already exists", carry on):
```
wrangler pages project create <slug> --production-branch=main
```
wrangler must be authed (`wrangler whoami`); if the token lacks `pages:write`, run `wrangler login` (opens John's browser — he clicks Allow). Then deploy — and for every future redeploy, this same one command:
```
cd ~/dev/<slug> && ./deploy.sh
```
Direct Upload bypasses the 500-builds/month limit. Verify against the LIVE url with curl:
- `/` returns 200 and the real `<title>`,
- `/assets/<logo>` returns 200 `content-type: image/png`,
- `/styles.css` returns 200.

## 5. Hand off
Give John the bare live URL on its own line (`https://<slug>.pages.dev`) — he asks for the link a lot, make it copy-pasteable. Then a tight recap: what shipped, `./deploy.sh` to update, and offer the two upsells (Instagram photo gallery; custom subdomain like `<slug>.yourstudio.dev`).

## 6. Record the client in the CRM
After the site is deployed and verified, add this business to the "Web Clients"
tab of John's CRM by shelling out to the CRM repo's stable CLI (it owns all the
DB/schema — don't touch the database directly, and don't import its Python):
```
python3 /Users/john/dev/contract_outreach/add_web_client.py \
  --company "<business name>" \
  --gbp "<google maps place url from §1>" \
  --phone "<business phone from §1>" \
  --site-url "https://<slug>.pages.dev"
```
Only `--company` is required; pass the others when known. This is best-effort —
if it exits non-zero (e.g. exit 3 = CRM/DB unavailable), mention it in the
handoff but do NOT treat it as a build failure; the site is already live.

## Guardrails
- Real data only. No fabricated prices, phone numbers, addresses, or fake photos/testimonials.
- Keep the client's real logo; don't rebrand them.
- Don't stand up a local http server; John opens the file directly.
- Don't `git` commit/push or delete infra unless told.
