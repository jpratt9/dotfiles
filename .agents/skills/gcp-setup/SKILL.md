---
name: gcp-setup
description: Create/configure a GCP project end-to-end with service account, APIs, and key file. No interactive auth needed after setup.
argument-hint: "<apis> for <project-name> [--account <email>] [--share <resource-id>]"
---

Set up a GCP project with service account credentials for automated access. Creates everything needed so scripts never require interactive `gcloud auth login` again.

## Steps

1. Run the setup script:
   ```
   python3 ~/.claude/skills/gcp-setup/scripts/gcp_setup.py "$ARGUMENTS"
   ```

2. If the script returns an error about authentication, run `gcloud auth login` to get an initial token, then re-run the script.

3. If the script succeeds, it will output JSON with:
   - `project_id`: The GCP project ID
   - `service_account_email`: The service account email (for sharing resources)
   - `key_file`: Path to the JSON key file
   - `apis_enabled`: List of APIs that were enabled
   - `shared_resources`: Any resources shared with the service account

4. Tell the user:
   - The key file location
   - The service account email (they may need to share Google Sheets/Drive files with this email)
   - How to use the key file in their code (show a Python snippet using `google.oauth2.service_account`)

## Usage Examples

```
/gcp-setup sheets,drive for gallitzin-repairs
/gcp-setup sheets for my-tracker --account john@john-pratt.com
/gcp-setup gmail,calendar,drive for personal-automation
```

## Notes

- Key files are stored in `~/.config/gcp-keys/<project-id>.json`
- If the project already exists, it reuses it and just ensures APIs + service account are set up
- The service account email must be shared on any Google Sheets/Drive resources it needs to access
- This replaces the need for `gcloud auth print-access-token` in scripts
