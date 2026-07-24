#!/usr/bin/env python3
"""Create a FormBackend form for a client site and (best-effort) set its
notification email + Cloudflare Turnstile keys via API.

Usage: python3 formbackend_form.py --name "Biz — estimate requests" [--email client@ex.com]
Reads FORMBACKEND_TOKEN, TURNSTILE_SITEKEY, TURNSTILE_SECRET from ../.env.
Exit: 0 ok (prints JSON w/ identifier), 3 no token, 4 API error.
"""
import argparse
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--email", default="")
    args = ap.parse_args()

    e = env()
    token = e.get("FORMBACKEND_TOKEN")
    if not token:
        print("FORMBACKEND_TOKEN missing in skill .env", file=sys.stderr)
        sys.exit(3)

    # extra fields are undocumented on create — harmless if ignored
    form = {"name": args.name}
    extra = {}
    if args.email:
        extra["notify_owner_emails"] = args.email
    if e.get("TURNSTILE_SITEKEY"):
        extra["cloudflare_turnstile_sitekey"] = e["TURNSTILE_SITEKEY"]
        extra["cloudflare_turnstile_secret"] = e["TURNSTILE_SECRET"]

    status, created = call("POST", API, token, {"form": {**form, **extra}})
    if status not in (200, 201) or not created.get("identifier"):
        print(f"create failed (HTTP {status}): {created}", file=sys.stderr)
        sys.exit(4)
    ident = created["identifier"]

    # probe the undocumented update path with the same extras
    patch_status = None
    if extra:
        patch_status, _ = call("PATCH", f"{API}/{ident}", token, {"form": extra})

    _, final = call("GET", f"{API}/{ident}", token)
    out = {
        "identifier": ident,
        "endpoint": f"https://www.formbackend.com/f/{ident}",
        "notify_owner_emails": final.get("notify_owner_emails"),
        "patch_http": patch_status,
        "dashboard_todo": [],
    }
    if args.email and final.get("notify_owner_emails") != args.email:
        out["dashboard_todo"].append("set notification email")
    if e.get("TURNSTILE_SITEKEY") and patch_status not in (200, 204):
        out["dashboard_todo"].append("paste Turnstile sitekey+secret in form Settings")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
