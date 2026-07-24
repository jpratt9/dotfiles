#!/usr/bin/env python3
"""Ensure a client hostname is covered by the current Turnstile widget.

Appends the hostname to the widget in .env; when there's no widget yet (or the
current one is full) it creates client-sites-NN and rewrites TURNSTILE_SITEKEY /
TURNSTILE_SECRET in the skill .env.

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

    # try appending to the current widget first
    sitekey = e.get("TURNSTILE_SITEKEY")
    if sitekey:
        status, res = call("GET", f"{base}/{sitekey}", token)
        if status == 200:
            w = res["result"]
            domains = w.get("domains", [])
            if args.hostname in domains:
                print(json.dumps({"action": "already-present", "sitekey": sitekey,
                                  "hostnames_used": len(domains)}))
                return
            if len(domains) < MAX_HOSTNAMES:
                status, res = call("PUT", f"{base}/{sitekey}", token, {
                    "name": w["name"], "mode": w.get("mode", "managed"),
                    "domains": domains + [args.hostname]})
                if status != 200:
                    print(f"append failed (HTTP {status}): {res.get('errors')}", file=sys.stderr)
                    sys.exit(4)
                print(json.dumps({"action": "appended", "sitekey": sitekey,
                                  "hostnames_used": len(domains) + 1}))
                return
        # fall through: widget gone or full → create a fresh one

    status, res = call("GET", f"{base}?per_page=50", token)
    existing = [w["name"] for w in res.get("result", [])] if status == 200 else []
    n = sum(1 for name in existing if name.startswith("client-sites-")) + 1
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
