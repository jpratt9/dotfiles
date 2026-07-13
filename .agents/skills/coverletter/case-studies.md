# John Pratt — Case Studies

Source material for professional summaries / cover letters. Condensed from
john-pratt.com/case-studies to the facts: what each project is, the results, the
stack, and the key accomplishments.

---

## Rainmaker — Agentic CRM / autonomous outbound engine
**What:** A serverless AI pipeline that runs B2B outbound end to end — fingerprints each target company's tech stack, resolves the right contact via Apollo.io, sends personalized cold email from real inboxes, then uses an LLM (Claude) to read and triage every reply.
**Status:** Personal project — live & running.
**Impact:** 100% hands-off · runs 24/7 · reply-triage every 15 min · 4 inboxes automated · ~$0 human hours/week.
**Stack:** Python, AWS Lambda, EventBridge, SQS, DynamoDB, Terraform, Apollo.io, Gmail API, Claude (Opus).
**Highlights:**
- Serverless and self-running on AWS Lambda + EventBridge (15-min cadence), with SQS backfill and DynamoDB idempotent dedup — all defined in Terraform.
- Per-company tech-stack fingerprinting (cloud provider, IaC, backend language) to personalize every touch.
- LLM reply classifier reads each inbound message and routes it (interview / lead / rejection / noise), parsing the gnarly HTML of LinkedIn and job-board notifications.
- Sends human-paced, personalized email across 4 real Gmail inboxes.

---

## Wraith — Autonomous Extraction Protocol
**What:** An autonomous video-extraction pipeline that authenticates, intercepts, and downloads encrypted streams from behind Cloudflare — across multiple sites, VPNs, and machines. Built after a platform sunset content he'd paid for (no export, no download button).
**Status:** Personal project — development complete.
**Impact:** 71K+ lines of code · 41 sites supported · 51K+ videos downloaded · 3 distributed machines · 40+ TB transferred.
**Stack:** Python, Selenium (undetected-chromedriver / UC mode), Cloudflare bypass, VPN orchestration, PostgreSQL, computer vision.
**Highlights:**
- Selenium UC-mode automation to authenticate and get past Cloudflare bot protection.
- VPN orchestration + distributed downloading across 3 machines for throughput and resilience.
- Scaled to 41 sites and 51K+ videos / 40+ TB, with PostgreSQL-backed state.

---

## Content Machine — Fully automated AI content engine
**What:** An AI-driven content engine that writes, designs, renders, and publishes short-form videos, blogs, and photos across platforms — completely on its own.
**Status:** Personal project — live & posting daily.
**Impact:** 500k+ views & impressions · 100% automated · 7+ content formats · 14+ distribution channels · ~$0 marginal cost/post.
**Stack:** LLMs, RAG, workflow automation, short-form video generation, SEO.
**Highlights:**
- End-to-end generation → publishing with no human in the loop; 500k+ views/impressions to date.
- 7+ content formats across 14+ distribution channels at ~$0 marginal cost per post.
- SEO-first blogs plus RAG-driven content generation.

---

## TALOS — Natural-Language Infrastructure as Code (client project)
**What:** Terraform-AI Language Orchestration System — turns plain-English prompts into compliant, deployed Terraform. Developers describe infrastructure in English; TALOS generates HCL via AWS Bedrock, secures every request with Cognito, and ships it through an automated CodePipeline.
**Status:** Client project — development complete.
**Impact:** Collapsed request-to-deployment from days of ticketing/handoffs to sub-hour pipelines; embedded compliance and governance into every prompt.
**Stack:** AWS Bedrock (generative AI), Terraform, Cognito, Lambda, CodePipeline/CodeBuild, S3 + DynamoDB backend, Node.js CLI, React web console.
**Highlights:**
- Bedrock generates Terraform from a hardened, audited module catalog; prompt engineering + policy checks prevent drift and insecure patterns.
- Zero-trust: Cognito-authenticated (JWT-validated) requests, role-segmented access, full auditability.
- Fully automated CI/CD: Lambda → CodePipeline runs `plan` in CodeBuild, surfaces diffs, then `apply`; S3-backed Terraform state with DynamoDB locks and deterministic rollbacks.

---

## UnitWolf — Zero-backend unit conversion at scale
**What:** A free, open-source unit-conversion platform — 18 categories, 100+ units, fully static, zero backend, global CDN delivery. Idea to production in 3 days.
**Status:** Personal project — development complete.
**Impact:** 69 pages generated · 18 categories · 100+ units · $0/month hosting · sub-100ms from 300+ CDN edge nodes.
**Stack:** React, TypeScript, Gatsby (SSG), Cloudflare Pages, Terraform.
**Highlights:**
- A single `UNIT_DEFINITIONS` data model drives UI, navigation, SEO metadata, and conversion logic — adding a unit is a data change, not a code change.
- 69 pages pre-rendered at build time, each with unique SEO metadata, canonical URLs, breadcrumbs, and related links.
- Hand-wrote a 34-line, string-based `Decimal` class to avoid JS floating-point errors without pulling in a math library; only temperature is special-cased (formula vs. factor).
- Entire infrastructure (Cloudflare Pages project, domain, DNS) managed as Terraform; 41 redirects preserved SEO across a URL restructure.

---

## Eagle Eye — Self-hosted, two-sense home security
**What:** A self-hosted home-security system with two senses: a camera that recognizes household members vs. strangers (local face recognition), and a passive radio scanner that catalogs every nearby Wi-Fi/Bluetooth device — surfacing the unknown (and surveillance-grade) ones to his phone in real time.
**Status:** Personal project — built and running unattended.
**Impact:** 2 sensing layers · 24/7 autonomous watch · 50K+ device fingerprints · real-time phone alerts.
**Stack:** Python, on-device facial recognition, SIGINT / passive RF scanning (Wi-Fi + Bluetooth).
**Highlights:**
- Local-only face recognition against a household allowlist — discards known/empty frames, alerts on strangers with the photo attached, security-tuned threshold.
- Passive (listen-only) RF scanner fingerprints device vendors against a 50K+ registry, estimates distance from signal strength, baselines household gear, and flags unknowns plus a watchlist (item trackers, drones, cellular field gear, surveillance-grade radios).
- Both senses resolve to one three-way verdict (known / unknown / watchlisted) → real-time phone push with evidence copied off-site.
- Self-healing always-on service that starts on boot, restarts after crashes, and reports its own failures.

---

## Cross-cutting themes (for a summary)
- **Autonomous, self-running systems** — several run 24/7 at ~$0 human hours (Rainmaker, Content Machine, Eagle Eye).
- **Serverless + Infrastructure-as-Code** — AWS Lambda/EventBridge/SQS/DynamoDB, Bedrock, Cognito, CodePipeline; everything Terraformed.
- **Applied AI / LLMs** — agentic pipelines, LLM classification and generation, RAG, on-device face recognition.
- **Full ownership** — owns data, infrastructure, orchestration, and the AI layer, from architecture through deployment.
- **Languages / tools** — Python, TypeScript / Node.js, React / Gatsby, Terraform, PostgreSQL, Cloudflare, multi-cloud (AWS / GCP / Azure).
