---
name: ship
description: Add unit tests for changes, run them, fix failures, commit, and push to GitHub
disable-model-invocation: false
---

Follow these steps in order:

1. **Add unit tests** for any new or changed code that isn't already covered. All external API/LLM calls must be MOCKED - do NOT call the actual external service in the unit tests
2. **Run all unit tests** and fix any failures, then re-run until all pass
3. **Re-deploy modified cloud infrastructure/remote code** (Lambda functions, Cloudflare Workers, etc.) with Terraform/etc if any changed files are part of an IaC-managed project
4. **Stage and commit** all changed files with an appropriate conventional commit message
5. **Push to GitHub**

Do NOT skip any step. Do NOT ask for confirmation between steps.
