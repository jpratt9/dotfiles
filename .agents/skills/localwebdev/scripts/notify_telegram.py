#!/usr/bin/env python3
"""Send the deployed site's URL to John's Telegram so he can open it on his
phone the instant it's live (test in mobile Chrome).

Secrets come from the environment, injected via `envchain telegram` — they are
NEVER hardcoded, because this skill lives in a public repo:
  TELEGRAM_BOT_TOKEN  (from @BotFather, e.g. 123456789:ABC...)
  TELEGRAM_CHAT_ID    (the destination chat id — John's own)

Stdlib only.

Usage:
  envchain telegram python3 notify_telegram.py --url https://<slug>.pages.dev [--name "Business"]

Exit codes: 0 sent · 1 send failed · 2 creds not injected (run under envchain).
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def main():
    ap = argparse.ArgumentParser(description="Telegram the live site URL to John.")
    ap.add_argument("--url", required=True, help="live site URL to send")
    ap.add_argument("--name", default="", help="business name for the message (optional)")
    args = ap.parse_args()

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[telegram] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — run under "
              "`envchain telegram`. Skipping notification.", file=sys.stderr)
        sys.exit(2)

    label = f"{args.name} — " if args.name else ""
    text = f"✅ {label}site is live:\n{args.url}"
    body = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=body)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            ok = json.loads(r.read().decode("utf-8")).get("ok", False)
    except urllib.error.HTTPError as e:
        print(f"[telegram] HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}",
              file=sys.stderr)
        sys.exit(1)
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"[telegram] request failed: {e}", file=sys.stderr)
        sys.exit(1)

    print("[telegram] sent" if ok else "[telegram] API returned not-ok")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
