#!/usr/bin/env python3
"""Set up the estimate form's backend for a client site. Takes NO arguments and
is fully idempotent — run it as many times as you like, from inside ~/dev/<slug>.

Everything is derived from the folder you're standing in:
    slug     = the folder name          (e.g. genzhaulers)
    hostname = <slug>.pages.dev
    form name = the slug, verbatim

It reuses the FormBackend form named after the slug, creating it only if absent
— so a rerun never mints a duplicate. Prints the endpoint to wire into the form.

No Turnstile here on purpose: FormBackend has no update API and ignores the
turnstile fields on create, so keys can ONLY be pasted in its dashboard by hand.
Use turnstile_widget.py separately if you ever do that.

Usage: cd ~/dev/<slug> && python3 formbackend_form.py
Reads FORMBACKEND_TOKEN from ../.env.
Exit: 0 ok (prints JSON), 3 no token, 4 API error.
"""
import json
import sys
from pathlib import Path

import requests

API = "https://www.formbackend.com/api/v1/forms"


def env():
    vals = {}
    p = Path(__file__).resolve().parent.parent / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                vals[k.strip()] = v.strip()
    return vals


def call(method, url, token, payload=None):
    """Return (status, body). The body is kept on 4xx/5xx too — FormBackend puts
    the reason for a refusal in there, so discarding it hides why a call failed."""
    try:
        r = requests.request(method, url, json=payload, timeout=30, headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    except requests.RequestException as e:
        return 0, {"error": str(e)}
    if not r.text.strip():
        return r.status_code, {}
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"error": r.text.strip()[:500]}


def find_form(slug, token):
    """Return the existing form named `slug`, or None. This is what makes reruns
    idempotent — without it every run mints another duplicate."""
    status, body = call("GET", API, token)
    if status != 200:
        return None
    forms = body if isinstance(body, list) else body.get("forms", [])
    for f in forms:
        if f.get("name") == slug:
            return f
    return None


def main():
    slug = Path.cwd().name

    e = env()
    token = e.get("FORMBACKEND_TOKEN")
    if not token:
        print("FORMBACKEND_TOKEN missing in skill .env", file=sys.stderr)
        sys.exit(3)

    # reuse the form named after this folder, create only if absent
    existing = find_form(slug, token)
    if existing:
        ident, reused = existing["identifier"], True
    else:
        status, created = call("POST", API, token, {"form": {"name": slug}})
        if status not in (200, 201) or not created.get("identifier"):
            print(f"create failed (HTTP {status}): {created}", file=sys.stderr)
            sys.exit(4)
        ident, reused = created["identifier"], False

    _, final = call("GET", f"{API}/{ident}", token)
    out = {
        "slug": slug,
        "identifier": ident,
        "endpoint": f"https://www.formbackend.com/f/{ident}",
        "reused_existing_form": reused,
        "notify_owner_emails": final.get("notify_owner_emails"),
        "notify_owner_on_submission": final.get("notify_owner_on_submission"),
        "blocking_dashboard_actions": [],
    }

    # FormBackend exposes no update endpoint (PATCH/PUT both 404), so anything
    # wrong here can ONLY be fixed by hand. These are not suggestions: a form
    # with notifications off accepts leads and silently emails nobody.
    if not final.get("notify_owner_on_submission"):
        out["blocking_dashboard_actions"].append(
            "turn ON 'notify owner on submission' — it is OFF by default, so leads "
            "are stored and NOBODY is emailed")
    if not final.get("notify_owner_emails"):
        out["blocking_dashboard_actions"].append("set the notification email address")

    print(json.dumps(out, indent=2))

    if out["blocking_dashboard_actions"]:
        print("\n" + "!" * 72, file=sys.stderr)
        print("BLOCKING — this form does NOT deliver leads yet. No API can fix these;",
              file=sys.stderr)
        print("open the FormBackend dashboard and do them by hand:", file=sys.stderr)
        for i, a in enumerate(out["blocking_dashboard_actions"], 1):
            print(f"  {i}. {a}", file=sys.stderr)
        print("!" * 72 + "\n", file=sys.stderr)


if __name__ == "__main__":
    main()
