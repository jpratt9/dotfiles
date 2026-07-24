#!/usr/bin/env python3
"""Ensure a client hostname is covered by a Turnstile widget, intelligently:

1. hostname already on any widget → done (sync .env keys when possible)
2. else append to a widget with spare room — the .env one first, then any other
   client-sites-* whose secret we can read; an append the API refuses (e.g.
   accounts capped below MAX_HOSTNAMES) just falls through
3. else create client-sites-NN (managed) and write its keys to .env

Usage: python3 turnstile_widget.py --hostname <slug>.pages.dev
Exit: 0 ok (prints JSON), 3 missing env vars, 4 API error.
"""
import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
MAX_HOSTNAMES = 15


def env():
    vals = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                vals[k.strip()] = v.strip()
    return vals


def save_env_keys(sitekey, secret):
    text = ENV_PATH.read_text()
    text = re.sub(r"^TURNSTILE_SITEKEY=.*$", f"TURNSTILE_SITEKEY={sitekey}", text, flags=re.M)
    text = re.sub(r"^TURNSTILE_SECRET=.*$", f"TURNSTILE_SECRET={secret}", text, flags=re.M)
    ENV_PATH.write_text(text)


def call(method, url, token, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"errors": [str(e)]}


def full_widget(base, token, w):
    """Return widget details incl. domains (list payloads may omit them)."""
    if "domains" in w:
        return w
    status, res = call("GET", f"{base}/{w['sitekey']}", token)
    return res.get("result", w) if status == 200 else w


def sync_env(e, w):
    """Point .env at widget w when we know its secret. Returns env_updated."""
    if w["sitekey"] == e.get("TURNSTILE_SITEKEY"):
        return False
    if w.get("secret"):
        save_env_keys(w["sitekey"], w["secret"])
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hostname", required=True)
    args = ap.parse_args()

    e = env()
    token, account = e.get("CLOUDFLARE_API_TOKEN"), e.get("CLOUDFLARE_ACCOUNT_ID")
    if not token or not account:
        print("CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID missing in skill .env", file=sys.stderr)
        sys.exit(3)
    base = f"https://api.cloudflare.com/client/v4/accounts/{account}/challenges/widgets"

    status, res = call("GET", f"{base}?per_page=50", token)
    if status != 200:
        print(f"list failed (HTTP {status}): {res.get('errors')}", file=sys.stderr)
        sys.exit(4)
    widgets = [full_widget(base, token, w) for w in res.get("result", [])]

    # 1) hostname already covered somewhere?
    for w in widgets:
        if args.hostname in w.get("domains", []):
            print(json.dumps({"action": "already-present", "widget": w.get("name"),
                              "sitekey": w["sitekey"], "env_updated": sync_env(e, w)}))
            return

    # 2) append to a widget with spare room we hold (or can learn) the secret for
    ordered = sorted(widgets, key=lambda w: w["sitekey"] != e.get("TURNSTILE_SITEKEY"))
    for w in ordered:
        domains = w.get("domains", [])
        usable = w["sitekey"] == e.get("TURNSTILE_SITEKEY") or w.get("secret")
        if len(domains) >= MAX_HOSTNAMES or not usable:
            continue
        status, put_res = call("PUT", f"{base}/{w['sitekey']}", token, {
            "name": w.get("name", "client-sites"), "mode": w.get("mode", "managed"),
            "domains": domains + [args.hostname]})
        if status == 200:
            print(json.dumps({"action": "appended", "widget": w.get("name"),
                              "sitekey": w["sitekey"], "hostnames_used": len(domains) + 1,
                              "env_updated": sync_env(e, w)}))
            return
        # refused (hard cap below MAX_HOSTNAMES, etc.) → try the next candidate

    # 3) mint a fresh widget
    n = sum(1 for w in widgets if str(w.get("name", "")).startswith("client-sites-")) + 1
    status, res = call("POST", base, token, {
        "name": f"client-sites-{n:02d}", "mode": "managed", "domains": [args.hostname]})
    if status != 200 or "result" not in res:
        print(f"create failed (HTTP {status}): {res.get('errors')}", file=sys.stderr)
        sys.exit(4)
    w = res["result"]
    save_env_keys(w["sitekey"], w["secret"])
    print(json.dumps({"action": "created", "widget": w["name"], "sitekey": w["sitekey"],
                      "env_updated": True,
                      "note": "new keypair — use these keys in FormBackend for this and future forms"}))


if __name__ == "__main__":
    main()
