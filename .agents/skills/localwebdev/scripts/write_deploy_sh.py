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
# Usage: ./deploy.sh          verify every page, then deploy
#        ./deploy.sh --check  verify only, don't deploy
set -euo pipefail
cd "$(dirname "$0")"

PROJECT="{project}"
CHECK_ONLY=0
[ "${{1:-}}" = "--check" ] && CHECK_ONLY=1

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

# Verify every page in public/ before anything ships: hard assertions (fold,
# overflow, broken images, form submit) AND a screen-by-screen filmstrip written
# to .verify/. Assertion failure aborts the deploy. The filmstrip is for eyes --
# nothing here can judge whether a page merely looks wrong, so READ THE FRAMES.
VERIFY="{verify}"
if [ -f "$VERIFY" ]; then
  for page in public/*.html; do
    [ -e "$page" ] || continue
    echo "→ verifying $(basename "$page") ..."
    set +e
    python3 "$VERIFY" --dir . --page "$(basename "$page")"
    v_rc=$?
    set -e
    # 4 = Chrome unavailable on this machine; not a fault in the site.
    if [ $v_rc -ne 0 ] && [ $v_rc -ne 4 ]; then
      echo "✗ $(basename "$page") failed verification (exit $v_rc) -- not deploying." >&2
      exit $v_rc
    fi
  done
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
  echo "✓ checks passed (--check: not deploying)"
  exit 0
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
    here = os.path.dirname(os.path.abspath(__file__))
    turnstile = os.path.join(here, "ensure_turnstile.py")
    verify = os.path.join(here, "verify_site.py")
    with open(path, "w") as f:
        f.write(TEMPLATE.format(project=args.project, name=name,
                                turnstile=turnstile, verify=verify))
    # chmod +x
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"wrote {path} (chmod +x)")


if __name__ == "__main__":
    main()
