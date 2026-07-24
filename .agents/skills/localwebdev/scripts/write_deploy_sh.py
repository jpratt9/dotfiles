#!/usr/bin/env python3
"""Write an executable deploy.sh into a localwebdev project dir.

The script wraps `wrangler pages deploy public` (Cloudflare Pages Direct Upload)
so deploy/redeploy is a one-liner: `./deploy.sh` (or `npm run deploy`).

Usage:
  python3 write_deploy_sh.py --project <slug> --dir ~/dev/<slug> [--name "<Business Name>"]
"""
import argparse
import os
import stat

TEMPLATE = '''#!/usr/bin/env bash
# Deploy / redeploy the {name} site to Cloudflare Pages (Direct Upload).
# Usage: ./deploy.sh   (or: npm run deploy)
set -euo pipefail
cd "$(dirname "$0")"

PROJECT="{project}"

# Ensure wrangler is available (installed as a devDependency).
if [ ! -x "node_modules/.bin/wrangler" ]; then
  echo "→ installing deps..."
  npm install
fi

# Cloudflare Pages serves _headers from the deploy dir. Rewrite it fresh on every
# deploy so the edge always revalidates and never serves a stale/cached copy --
# this is what stops PageSpeed Insights (and browsers) from testing an old version.
mkdir -p public
cat > public/_headers <<'HEADERS'
/*
  Cache-Control: public, max-age=0, must-revalidate
HEADERS

# Guarantee Cloudflare Turnstile is wired into the built site: api.js in the
# <head> of any page carrying a form, a .cf-turnstile div inside every form, and
# the .turnstile-box rule in the stylesheet. Idempotent -- it only edits what is
# missing, so it is a no-op on every deploy after the first. Skipped silently
# when the skill isn't on this machine (e.g. a fresh clone of this repo).
TURNSTILE="{turnstile}"
if [ -f "$TURNSTILE" ]; then
  echo "→ ensuring Turnstile..."
  set +e
  python3 "$TURNSTILE" --dir public
  ts_rc=$?
  set -e
  # exit 2 = no sitekey configured, which is a config choice rather than a fault.
  if [ $ts_rc -ne 0 ] && [ $ts_rc -ne 2 ]; then
    echo "✗ turnstile injection failed (exit $ts_rc)" >&2
    exit $ts_rc
  fi
fi

echo "→ deploying ./public to ${{PROJECT}}.pages.dev ..."
node_modules/.bin/wrangler pages deploy public \\
  --project-name="${{PROJECT}}" \\
  --branch=main \\
  --commit-dirty=true

echo "✓ done → https://${{PROJECT}}.pages.dev"
'''


def main():
    ap = argparse.ArgumentParser(description="Write deploy.sh for a localwebdev project.")
    ap.add_argument("--project", required=True, help="Cloudflare Pages project name / slug")
    ap.add_argument("--dir", required=True, help="project root to write deploy.sh into")
    ap.add_argument("--name", help="human-readable business name for the comment (defaults to --project)")
    args = ap.parse_args()

    name = args.name or args.project
    path = os.path.join(os.path.expanduser(args.dir), "deploy.sh")
    turnstile = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ensure_turnstile.py")
    with open(path, "w") as f:
        f.write(TEMPLATE.format(project=args.project, name=name, turnstile=turnstile))
    # chmod +x
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"wrote {path} (chmod +x)")


if __name__ == "__main__":
    main()
