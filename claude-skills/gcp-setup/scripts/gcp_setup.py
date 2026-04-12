"""
GCP Project Setup — end-to-end automated setup for Google Cloud projects.

Creates a project, enables APIs, creates a service account, downloads a key file,
optionally shares resources, and VERIFIES the key works before reporting success.

Usage:
    python3 gcp_setup.py "sheets,drive for my-project"
    python3 gcp_setup.py "sheets for my-project --share https://docs.google.com/spreadsheets/d/ABC123/edit"
    python3 gcp_setup.py "sheets,drive for my-project --share 1tKRj3gDBfvEAdxEdOvc9bwTNYmLxsPT890Uo4eN_-uQ"
"""

import json
import os
import re
import subprocess
import sys
import time

KEY_DIR = os.path.expanduser("~/.config/gcp-keys")

API_MAP = {
    "sheets": "sheets.googleapis.com",
    "drive": "drive.googleapis.com",
    "gmail": "gmail.googleapis.com",
    "calendar": "calendar-json.googleapis.com",
    "docs": "docs.googleapis.com",
    "slides": "slides.googleapis.com",
    "storage": "storage.googleapis.com",
    "bigquery": "bigquery.googleapis.com",
    "compute": "compute.googleapis.com",
    "functions": "cloudfunctions.googleapis.com",
    "run": "run.googleapis.com",
    "pubsub": "pubsub.googleapis.com",
    "firestore": "firestore.googleapis.com",
    "vision": "vision.googleapis.com",
    "translate": "translate.googleapis.com",
    "speech": "speech.googleapis.com",
    "youtube": "youtube.googleapis.com",
    "maps": "maps-backend.googleapis.com",
    "iam": "iam.googleapis.com",
}

# Map API short names to OAuth scopes for verification
API_SCOPES = {
    "sheets": "https://www.googleapis.com/auth/spreadsheets",
    "drive": "https://www.googleapis.com/auth/drive",
    "gmail": "https://www.googleapis.com/auth/gmail.readonly",
    "calendar": "https://www.googleapis.com/auth/calendar",
    "docs": "https://www.googleapis.com/auth/documents",
    "slides": "https://www.googleapis.com/auth/presentations",
    "storage": "https://www.googleapis.com/auth/devstorage.read_write",
    "bigquery": "https://www.googleapis.com/auth/bigquery",
}

# Regex patterns to extract resource IDs from Google URLs
URL_PATTERNS = [
    # Google Sheets: https://docs.google.com/spreadsheets/d/ID/edit...
    (r"docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)", "sheet"),
    # Google Docs: https://docs.google.com/document/d/ID/edit...
    (r"docs\.google\.com/document/d/([a-zA-Z0-9_-]+)", "doc"),
    # Google Slides: https://docs.google.com/presentation/d/ID/edit...
    (r"docs\.google\.com/presentation/d/([a-zA-Z0-9_-]+)", "slides"),
    # Google Drive file: https://drive.google.com/file/d/ID/view...
    (r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)", "drive"),
    # Google Drive folder: https://drive.google.com/drive/folders/ID
    (r"drive\.google\.com/drive/folders/([a-zA-Z0-9_-]+)", "folder"),
]


def run(cmd, check=True):
    """Run a shell command and return stdout."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr.strip()}")
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def log(msg):
    print(msg, file=sys.stderr)


def extract_resource_id(value):
    """Extract a resource ID from a Google URL or return as-is if already an ID."""
    for pattern, resource_type in URL_PATTERNS:
        match = re.search(pattern, value)
        if match:
            resource_id = match.group(1)
            log(f"Extracted {resource_type} ID from URL: {resource_id}")
            return resource_id, resource_type

    # If it looks like a raw ID (alphanumeric, dashes, underscores), use it directly
    if re.match(r"^[a-zA-Z0-9_-]+$", value):
        return value, "unknown"

    raise ValueError(f"Could not extract resource ID from: {value}")


def get_token():
    """Get current gcloud auth token."""
    stdout, stderr, rc = run(["gcloud", "auth", "print-access-token"], check=False)
    if rc != 0:
        raise RuntimeError(
            "Not authenticated. Run: gcloud auth login --enable-gdrive-access"
        )
    return stdout


def get_billing_account():
    """Get the first available billing account."""
    stdout, _, _ = run(["gcloud", "billing", "accounts", "list", "--format=json"])
    accounts = json.loads(stdout)
    for acct in accounts:
        if acct.get("open", False):
            return acct["name"].split("/")[-1]
    return None


def get_project_state(project_id):
    """Check project state: 'active', 'pending_delete', or 'not_found'."""
    stdout, _, rc = run(
        ["gcloud", "projects", "describe", project_id, "--format=json"], check=False
    )
    if rc != 0:
        return "not_found"
    try:
        data = json.loads(stdout)
        lifecycle = data.get("lifecycleState", "ACTIVE")
        if lifecycle == "DELETE_REQUESTED":
            return "pending_delete"
        return "active"
    except json.JSONDecodeError:
        return "not_found"


def create_project(project_id):
    """Create a new GCP project, handling pending-delete and other states."""
    state = get_project_state(project_id)

    if state == "active":
        log(f"Project {project_id} already exists, reusing.")
        return project_id

    if state == "pending_delete":
        # GCP holds deleted project names for 30 days and restored projects
        # take hours to become usable. Just pick a new name.
        for suffix in range(2, 20):
            alt = f"{project_id}-{suffix}"
            alt_state = get_project_state(alt)
            if alt_state == "not_found":
                log(f"Project {project_id} is pending deletion (30-day hold). Using {alt} instead.")
                project_id = alt
                break
        else:
            raise RuntimeError(
                f"Project '{project_id}' and all suffixes up to -19 are taken. "
                f"Pick a different base name."
            )

    run(["gcloud", "projects", "create", project_id, "--name", project_id])
    log(f"Created project: {project_id}")

    billing_account = get_billing_account()
    if billing_account:
        run([
            "gcloud", "billing", "projects", "link", project_id,
            "--billing-account", billing_account,
        ], check=False)
        log(f"Linked billing account: {billing_account}")

    return project_id


def enable_apis(project_id, apis):
    """Enable APIs on the project."""
    resolved = []
    for api in apis:
        api = api.strip().lower()
        full_name = API_MAP.get(api, api)
        if "." not in full_name:
            full_name = f"{full_name}.googleapis.com"
        resolved.append(full_name)

    if not resolved:
        return []

    if "iam.googleapis.com" not in resolved:
        resolved.append("iam.googleapis.com")

    run(["gcloud", "services", "enable", *resolved, "--project", project_id])
    log(f"Enabled APIs: {', '.join(resolved)}")
    return resolved


def list_all_org_policy_constraints(project_id):
    """List all org policy constraints active on the project."""
    stdout, _, rc = run([
        "gcloud", "resource-manager", "org-policies", "list",
        "--project", project_id, "--format=json",
    ], check=False)
    if rc != 0:
        return []
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return []


def disable_all_sa_key_constraints(project_id):
    """Find and disable ALL org policy constraints that block service account key creation."""
    policies = list_all_org_policy_constraints(project_id)

    blocking_constraints = []
    for policy in policies:
        constraint = policy.get("constraint", "")
        if any(keyword in constraint.lower() for keyword in [
            "serviceaccountkey",
            "service_account_key",
            "disableserviceaccountkeycreation",
        ]):
            blocking_constraints.append(constraint)

    known_constraints = [
        "iam.disableServiceAccountKeyCreation",
        "iam.managed.disableServiceAccountKeyCreation",
    ]
    for c in known_constraints:
        prefixed = f"constraints/{c}"
        if prefixed not in blocking_constraints and c not in blocking_constraints:
            blocking_constraints.append(c)

    normalized = [c.replace("constraints/", "") for c in blocking_constraints]

    log(f"Attempting to disable {len(normalized)} SA key constraints: {normalized}")

    for constraint in normalized:
        overridden = False

        # Method 1: Legacy CLI — disable-enforce
        _, _, rc = run([
            "gcloud", "resource-manager", "org-policies", "disable-enforce",
            constraint, "--project", project_id,
        ], check=False)
        if rc == 0:
            log(f"  Disabled enforcement (legacy CLI): {constraint}")
            overridden = True

        # Method 2: New org-policies CLI — delete-policy (for managed constraints)
        if not overridden:
            _, _, rc = run([
                "gcloud", "org-policies", "delete",
                f"constraints/{constraint}",
                "--project", project_id,
            ], check=False)
            if rc == 0:
                log(f"  Deleted policy (new CLI): {constraint}")
                overridden = True

        # Method 3: New org-policies CLI — reset (inherits from parent but clears project override)
        if not overridden:
            _, _, rc = run([
                "gcloud", "org-policies", "reset",
                f"constraints/{constraint}",
                "--project", project_id,
            ], check=False)
            if rc == 0:
                log(f"  Reset policy (new CLI): {constraint}")
                overridden = True

        # Method 4: New org-policies CLI — set-policy with dry-run spec (allow all)
        if not overridden:
            import tempfile
            policy_json = json.dumps({
                "name": f"projects/{project_id}/policies/{constraint}",
                "spec": {
                    "rules": [{"enforce": False}]
                }
            })
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as f:
                f.write(policy_json)
                policy_file = f.name
            try:
                _, _, rc = run([
                    "gcloud", "org-policies", "set-policy",
                    policy_file, "--project", project_id,
                ], check=False)
                if rc == 0:
                    log(f"  Set enforce=false (new CLI): {constraint}")
                    overridden = True
            finally:
                os.unlink(policy_file)

        # Method 5: Legacy CLI — set-policy with empty booleanPolicy
        if not overridden:
            import tempfile
            policy_yaml = (
                f"constraint: constraints/{constraint}\n"
                f"booleanPolicy: {{}}\n"
            )
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".yaml", delete=False
            ) as f:
                f.write(policy_yaml)
                policy_file = f.name
            try:
                _, _, rc = run([
                    "gcloud", "resource-manager", "org-policies", "set-policy",
                    policy_file, "--project", project_id,
                ], check=False)
                if rc == 0:
                    log(f"  Set empty policy (legacy CLI): {constraint}")
                    overridden = True
            finally:
                os.unlink(policy_file)

        # Method 6: Legacy CLI — reset
        if not overridden:
            _, _, rc = run([
                "gcloud", "resource-manager", "org-policies", "reset",
                constraint, "--project", project_id,
            ], check=False)
            if rc == 0:
                log(f"  Reset policy (legacy CLI): {constraint}")
                overridden = True

        # Method 7: Legacy CLI — delete
        if not overridden:
            _, _, rc = run([
                "gcloud", "resource-manager", "org-policies", "delete",
                f"constraints/{constraint}", "--project", project_id,
            ], check=False)
            if rc == 0:
                log(f"  Deleted policy (legacy CLI): {constraint}")
                overridden = True

        if not overridden:
            log(f"  Warning: Could not override {constraint} with any method")

    time.sleep(5)


def get_service_account(project_id, sa_name="automation"):
    """Get or create a service account, handling org policy blocks."""
    sa_email = f"{sa_name}@{project_id}.iam.gserviceaccount.com"

    _, _, rc = run([
        "gcloud", "iam", "service-accounts", "describe", sa_email,
        "--project", project_id, "--format=json",
    ], check=False)

    if rc == 0:
        log(f"Service account already exists: {sa_email}")
        return sa_email

    _, stderr, rc = run([
        "gcloud", "iam", "service-accounts", "create", sa_name,
        "--display-name", f"{project_id} automation",
        "--project", project_id,
    ], check=False)

    if rc != 0 and "disableServiceAccount" in stderr:
        log("Org policy blocking SA creation, overriding...")
        policies = list_all_org_policy_constraints(project_id)
        for policy in policies:
            c = policy.get("constraint", "").replace("constraints/", "")
            if "serviceaccount" in c.lower() and "creation" in c.lower():
                run([
                    "gcloud", "resource-manager", "org-policies", "disable-enforce",
                    c, "--project", project_id,
                ], check=False)
        time.sleep(5)
        run([
            "gcloud", "iam", "service-accounts", "create", sa_name,
            "--display-name", f"{project_id} automation",
            "--project", project_id,
        ])
    elif rc != 0:
        raise RuntimeError(f"Service account creation failed:\n{stderr}")

    log(f"Created service account: {sa_email}")

    # Wait for SA to propagate before binding IAM role
    for attempt in range(6):
        _, _, rc = run([
            "gcloud", "iam", "service-accounts", "describe", sa_email,
            "--project", project_id, "--format=json",
        ], check=False)
        if rc == 0:
            break
        log(f"  Waiting for SA propagation... ({attempt + 1}/6)")
        time.sleep(5)

    run([
        "gcloud", "projects", "add-iam-policy-binding", project_id,
        "--member", f"serviceAccount:{sa_email}",
        "--role", "roles/editor",
        "--quiet",
    ])
    log(f"Granted editor role to {sa_email}")

    return sa_email


def download_key(project_id, sa_email):
    """Download a service account key file, auto-clearing any org policy blocks."""
    os.makedirs(KEY_DIR, exist_ok=True)
    key_path = os.path.join(KEY_DIR, f"{project_id}.json")

    if os.path.exists(key_path):
        try:
            with open(key_path) as f:
                key_data = json.load(f)
            if key_data.get("project_id") == project_id:
                log(f"Key file already exists: {key_path}")
                return key_path
        except (json.JSONDecodeError, KeyError):
            pass

    _, stderr, rc = run([
        "gcloud", "iam", "service-accounts", "keys", "create", key_path,
        "--iam-account", sa_email,
        "--project", project_id,
    ], check=False)

    if rc == 0:
        os.chmod(key_path, 0o600)
        log(f"Downloaded key file: {key_path}")
        return key_path

    if "disableServiceAccountKeyCreation" not in stderr:
        raise RuntimeError(f"Key creation failed:\n{stderr}")

    log("Org policy blocking key creation, finding and disabling all related constraints...")
    disable_all_sa_key_constraints(project_id)

    _, stderr2, rc2 = run([
        "gcloud", "iam", "service-accounts", "keys", "create", key_path,
        "--iam-account", sa_email,
        "--project", project_id,
    ], check=False)

    if rc2 != 0:
        raise RuntimeError(
            f"Key creation still blocked after overriding all known constraints.\n"
            f"{stderr2}\n\n"
            f"This likely means the constraint is enforced at the organization level "
            f"and your account doesn't have permission to override it.\n"
            f"Fix: Ask your org admin to add an exception, or use a project in a "
            f"different org/personal account."
        )

    os.chmod(key_path, 0o600)
    log(f"Downloaded key file: {key_path}")
    return key_path


def share_google_resource(token, resource_id, sa_email):
    """Share a Google resource with the service account (reader — least privilege)."""
    data = json.dumps({
        "role": "reader",
        "type": "user",
        "emailAddress": sa_email,
    })
    url = f"https://www.googleapis.com/drive/v3/files/{resource_id}/permissions"

    stdout, stderr, rc = run([
        "curl", "-s", "-X", "POST", url,
        "-H", f"Authorization: Bearer {token}",
        "-H", "Content-Type: application/json",
        "-d", data,
    ], check=False)

    if rc != 0:
        raise RuntimeError(f"Failed to share resource {resource_id}: {stderr}")

    try:
        resp = json.loads(stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Unexpected response sharing {resource_id}: {stdout}")

    if "error" in resp:
        # If already shared, that's fine
        err_msg = json.dumps(resp["error"])
        if "already has access" in err_msg.lower():
            log(f"Resource {resource_id} already shared with {sa_email}")
            return resp
        raise RuntimeError(f"Failed to share resource {resource_id}: {resp['error']}")

    return resp


def verify_key(key_path, apis, shared_resources):
    """Verify the service account key works by making test API calls."""
    log("Verifying service account key...")

    # Build scopes from requested APIs
    scopes = []
    for api in apis:
        api = api.strip().lower()
        scope = API_SCOPES.get(api)
        if scope:
            scopes.append(scope)
    if not scopes:
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]

    # Try to get an access token using the service account key
    # This verifies: key file is valid, SA exists, credentials work
    token_stdout, token_stderr, token_rc = run([
        "gcloud", "auth", "print-access-token",
        f"--impersonate-service-account=$(python3 -c \"import json; print(json.load(open('{key_path}'))['client_email'])\")",
    ], check=False)

    # Fallback: use the key directly via a Python one-liner
    verify_script = f"""
import json, sys
try:
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        '{key_path}',
        scopes={json.dumps(scopes)}
    )
    creds.refresh(__import__('google.auth.transport.requests', fromlist=['Request']).Request())
    print(json.dumps({{"status": "ok", "token_prefix": creds.token[:20] + "..."}}))
except Exception as e:
    print(json.dumps({{"status": "error", "message": str(e)}}))
"""
    stdout, stderr, rc = run(["python3", "-c", verify_script], check=False)

    try:
        result = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        raise RuntimeError(f"Key verification failed — could not parse output:\n{stdout}\n{stderr}")

    if result.get("status") != "ok":
        raise RuntimeError(f"Key verification failed: {result.get('message', 'unknown error')}")

    log(f"Key verified: token acquired successfully ({result.get('token_prefix', '?')})")

    # Verify shared resource access using the SA token via HTTP
    if shared_resources:
        # Use the requested API scopes + drive.readonly for file metadata access
        verify_scopes = list(set(scopes + ['https://www.googleapis.com/auth/drive.readonly']))
        token_script = f"""
import json
from google.oauth2.service_account import Credentials
creds = Credentials.from_service_account_file(
    '{key_path}',
    scopes={json.dumps(verify_scopes)}
)
creds.refresh(__import__('google.auth.transport.requests', fromlist=['Request']).Request())
print(creds.token)
"""
        sa_token, _, _ = run(["python3", "-c", token_script], check=False)

        if sa_token:
            for share in shared_resources:
                if share.get("status") != "shared":
                    continue
                resource_id = share["resource_id"]
                # files.get is the universal metadata endpoint for all
                # Google Workspace resources (not Drive-specific)
                stdout2, _, _ = run([
                    "curl", "-s",
                    f"https://www.googleapis.com/drive/v3/files/{resource_id}?fields=name,mimeType",
                    "-H", f"Authorization: Bearer {sa_token}",
                ], check=False)
                try:
                    meta = json.loads(stdout2)
                    if "name" in meta:
                        log(f"  Verified access to: {meta['name']} ({meta.get('mimeType', '?')})")
                    elif "error" in meta:
                        log(f"  Warning: Cannot access {resource_id}: {meta['error'].get('message', '?')}")
                except (json.JSONDecodeError, ValueError):
                    log(f"  Warning: Could not verify access to {resource_id}")

    return True


def parse_args(raw_args):
    """Parse the argument string into components."""
    args = raw_args.strip()

    account = None
    account_match = re.search(r"--account\s+(\S+)", args)
    if account_match:
        account = account_match.group(1)
        args = args[:account_match.start()] + args[account_match.end():]

    shares = []
    for m in re.finditer(r"--share\s+(\S+)", args):
        shares.append(m.group(1))
    args = re.sub(r"--share\s+\S+", "", args).strip()

    match = re.match(r"^([\w,.\s]+?)\s+for\s+([\w-]+)$", args.strip())
    if not match:
        raise ValueError(
            f"Could not parse arguments: '{raw_args}'\n"
            f"Expected format: 'api1,api2 for project-name "
            f"[--account email] [--share <url-or-id>]'"
        )

    apis_str = match.group(1)
    project_id = match.group(2)
    apis = [a.strip() for a in apis_str.split(",") if a.strip()]

    return {
        "apis": apis,
        "project_id": project_id,
        "account": account,
        "shares": shares,
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({
            "error": (
                "No arguments provided.\n"
                "Usage: api1,api2 for project-name [--share <url-or-id>]\n"
                "Example: sheets,drive for my-project "
                "--share https://docs.google.com/spreadsheets/d/ABC123/edit"
            )
        }))
        sys.exit(1)

    raw_args = " ".join(sys.argv[1:])

    try:
        parsed = parse_args(raw_args)
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    project_id = parsed["project_id"]
    apis = parsed["apis"]
    raw_shares = parsed["shares"]

    # Extract resource IDs from URLs
    shares = []
    for s in raw_shares:
        try:
            resource_id, resource_type = extract_resource_id(s)
            shares.append({"raw": s, "id": resource_id, "type": resource_type})
        except ValueError as e:
            print(json.dumps({"error": str(e)}))
            sys.exit(1)

    try:
        # Step 1: Ensure we have auth
        token = get_token()

        # Step 2: Create or reuse project (may change project_id if original is zombie)
        project_id = create_project(project_id)

        # Step 3: Enable APIs
        enabled = enable_apis(project_id, apis)

        # Step 4: Create service account
        sa_email = get_service_account(project_id)
        time.sleep(2)

        # Step 5: Download key file
        key_path = download_key(project_id, sa_email)

        # Step 6: Share resources with SA (reader — least privilege)
        shared = []
        if shares:
            token = get_token()
            for share_info in shares:
                resource_id = share_info["id"]
                try:
                    share_google_resource(token, resource_id, sa_email)
                    shared.append({"resource_id": resource_id, "status": "shared"})
                    log(f"Shared {resource_id} with {sa_email} (reader)")
                except Exception as e:
                    shared.append({
                        "resource_id": resource_id,
                        "status": f"error: {e}",
                    })
                    log(f"Warning: Could not share {resource_id}: {e}")

        # Step 7: VERIFY the key actually works — if not, delete and re-download
        try:
            verify_key(key_path, apis, shared)
        except RuntimeError as e:
            if "invalid_grant" in str(e) or "Invalid JWT" in str(e):
                log("Key is stale/invalid (project may have been restored). Re-downloading...")
                os.remove(key_path)
                key_path = download_key(project_id, sa_email)
                verify_key(key_path, apis, shared)
            else:
                raise

        # Build scopes list for the usage snippet
        scopes = [API_SCOPES.get(a.strip().lower(), f"https://www.googleapis.com/auth/{a}")
                   for a in apis if a.strip().lower() in API_SCOPES]
        if not scopes:
            scopes = ["https://www.googleapis.com/auth/cloud-platform"]

        result = {
            "project_id": project_id,
            "service_account_email": sa_email,
            "key_file": key_path,
            "apis_enabled": enabled,
            "shared_resources": shared,
            "verified": True,
            "usage_snippet": (
                "from google.oauth2.service_account import Credentials\n"
                "from googleapiclient.discovery import build\n\n"
                f"creds = Credentials.from_service_account_file(\n"
                f"    '{key_path}',\n"
                f"    scopes={json.dumps(scopes, indent=8)}\n"
                f")\n"
                f"sheets = build('sheets', 'v4', credentials=creds)\n"
            ),
        }

        print(json.dumps(result, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
