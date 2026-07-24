"""User-OAuth credentials for APIs that a service account cannot reach.

Service accounts work fine for Sheets/Drive/BigQuery, but they cannot touch a
consumer @gmail.com mailbox: the SA has no mailbox of its own, and impersonating
the user needs domain-wide delegation, which only a Google Workspace admin can
grant. For those APIs we need three-legged user OAuth instead.

This module obtains and caches a user refresh token, printing the auth URL so
the caller can click it once. Tokens are cached in KEY_DIR and reused forever
after, provided the consent screen is published (see PUBLISH_HINT).

Usable as a library (`ensure_user_credentials`) or standalone:
    python3 user_oauth.py <project_id> <scope> [<scope> ...]
"""

import glob
import json
import os
import subprocess
import sys

KEY_DIR = os.path.expanduser("~/.config/gcp-keys")
VENV_DIR = os.path.join(KEY_DIR, ".venv")
DEPS = ["google-auth-oauthlib", "google-api-python-client"]


class MissingClientSecret(RuntimeError):
    """No OAuth client for this project; a human must create one once."""


def log(msg):
    print(msg, file=sys.stderr)


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def project_number(project_id):
    """Look up the numeric project number, used to match downloaded secrets.

    Falls back to every authenticated account, since the active one is often
    not the account that owns the project.
    """
    def describe(*extra):
        r = _run(["gcloud", "projects", "describe", project_id,
                  "--format=value(projectNumber)", *extra])
        return r.stdout.strip() if r.returncode == 0 else ""

    num = describe()
    if num:
        return num
    accounts = _run(["gcloud", "auth", "list", "--format=value(account)"]).stdout.split()
    for account in accounts:
        num = describe(f"--account={account}")
        if num:
            return num
    return None


def console_urls(project_id):
    base = "https://console.cloud.google.com"
    return (
        f"{base}/auth/clients/create?project={project_id}",
        f"{base}/auth/audience?project={project_id}",
    )


def find_client_secret(project_id):
    """Locate an OAuth client secret JSON for this project.

    Looks in KEY_DIR first, then ~/Downloads for a file whose name carries this
    project's number — Downloads usually holds secrets from several projects, so
    matching on the number avoids grabbing the wrong one.
    """
    pinned = os.path.join(KEY_DIR, f"{project_id}-client.json")
    if os.path.exists(pinned):
        return pinned

    num = project_number(project_id)
    if num:
        hits = sorted(glob.glob(
            os.path.expanduser(f"~/Downloads/client_secret_{num}-*.json")))
        if hits:
            os.makedirs(KEY_DIR, exist_ok=True)
            os.replace(hits[-1], pinned)
            log(f"Adopted downloaded OAuth client -> {pinned}")
            return pinned
    return None


def _python_with_deps():
    """Return an interpreter that can import the Google OAuth libraries.

    Prefers the current one; otherwise builds a small venv under KEY_DIR so the
    caller never has to think about dependencies.
    """
    probe = "import google_auth_oauthlib, googleapiclient"
    if _run([sys.executable, "-c", probe]).returncode == 0:
        return sys.executable

    venv_py = os.path.join(VENV_DIR, "bin", "python")
    if not os.path.exists(venv_py):
        log(f"Creating helper venv at {VENV_DIR} ...")
        _run([sys.executable, "-m", "venv", VENV_DIR])
    if _run([venv_py, "-c", probe]).returncode != 0:
        log(f"Installing {', '.join(DEPS)} ...")
        _run([venv_py, "-m", "pip", "install", "--quiet", *DEPS])
    if _run([venv_py, "-c", probe]).returncode != 0:
        raise RuntimeError(f"Could not provision dependencies into {VENV_DIR}")
    return venv_py


# Runs in the interpreter that has the Google libs; prints the auth URL, opens a
# loopback listener, and writes the resulting token. Kept as a string so the
# parent process needs no dependencies of its own.
_FLOW = r"""
import json, sys
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

client_secret, token_path, scopes = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])

creds = None
try:
    creds = Credentials.from_authorized_user_file(token_path, scopes)
except Exception:
    creds = None

if creds and not creds.valid and creds.refresh_token:
    try:
        creds.refresh(Request())
    except RefreshError:
        creds = None

if not creds or not creds.valid:
    flow = InstalledAppFlow.from_client_secrets_file(client_secret, scopes)
    creds = flow.run_local_server(
        port=0, open_browser=False,
        authorization_prompt_message="\n>>> Open this URL and approve:\n\n{url}\n",
        success_message="Authorized. You can close this tab.",
    )

with open(token_path, "w") as fh:
    fh.write(creds.to_json())
print(json.dumps({"status": "ok", "token": token_path}))
"""


def ensure_user_credentials(project_id, scopes, force=False):
    """Return the path to a cached user-OAuth token for this project.

    Raises MissingClientSecret if no OAuth client exists yet — that step needs a
    human, because Google shut down the only API that could create one.
    """
    os.makedirs(KEY_DIR, exist_ok=True)
    token_path = os.path.join(KEY_DIR, f"{project_id}-user-token.json")
    if force and os.path.exists(token_path):
        os.remove(token_path)

    client_secret = find_client_secret(project_id)
    if not client_secret:
        raise MissingClientSecret(project_id)

    py = _python_with_deps()
    proc = subprocess.run(
        [py, "-c", _FLOW, client_secret, token_path, json.dumps(list(scopes))],
        text=True, capture_output=False,
    )
    if proc.returncode != 0 or not os.path.exists(token_path):
        raise RuntimeError("User OAuth flow did not complete.")
    os.chmod(token_path, 0o600)
    return token_path


def instructions(project_id):
    """Human-readable steps for the one part that cannot be automated."""
    create_url, audience_url = console_urls(project_id)
    num = project_number(project_id) or "<project-number>"
    return (
        "This API needs user OAuth, and Google removed the API that used to\n"
        "create OAuth clients (IAP OAuth Admin APIs, shut down 2026-03-19), so\n"
        "this one step must be done by hand, once per project:\n\n"
        f"  1. {create_url}\n"
        "     Application type: Desktop app -> Create -> Download JSON\n\n"
        f"  2. {audience_url}\n"
        "     Click 'Publish app' so status reads 'In production'.\n"
        "     (In 'Testing' the refresh token dies after 7 days. The expiry is\n"
        "     keyed on publishing status, not on which scopes you ask for.)\n\n"
        "     Do step 2 BEFORE consenting. Consenting while still in 'Testing'\n"
        "     banks a 7-day token, and you have to redo the consent after\n"
        "     publishing to get a durable one.\n\n"
        f"Leave the download in ~/Downloads (named client_secret_{num}-*.json)\n"
        "or move it to "
        f"{os.path.join(KEY_DIR, project_id + '-client.json')}, then re-run.\n"
        "Everything after that is automatic."
    )


def main():
    if len(sys.argv) < 3:
        sys.exit("usage: user_oauth.py <project_id> <scope> [<scope> ...]")
    project_id, scopes = sys.argv[1], sys.argv[2:]
    try:
        token = ensure_user_credentials(project_id, scopes)
    except MissingClientSecret:
        print(instructions(project_id), file=sys.stderr)
        sys.exit(2)
    print(json.dumps({"token_file": token, "scopes": scopes}, indent=2))


if __name__ == "__main__":
    main()
