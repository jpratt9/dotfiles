#!/bin/bash
# Enable GDM3 autologin on a remote Debian/Ubuntu box over SSH, so it boots
# straight to the desktop instead of stopping at the graphical login greeter.
#
# This is exactly what was done by hand on elitedesk-debian: edit
# /etc/gdm3/daemon.conf to set AutomaticLogin* for the user, then restart gdm.
#
# Usage: gdm-autologin.sh <username> <password> <host-or-ip>
#   <password> is used for BOTH the SSH login and the remote sudo.
#
# Requires: sshpass (brew install sshpass)

set -euo pipefail

if [[ $# -ne 3 ]]; then
    echo "Usage: $(basename "$0") <username> <password> <host-or-ip>" >&2
    exit 1
fi

USER_NAME="$1"
PASSWORD="$2"
HOST="$3"

if ! command -v sshpass >/dev/null 2>&1; then
    echo "error: sshpass not installed (brew install sshpass)" >&2
    exit 1
fi

# Remote commands: back up daemon.conf once, set autologin for this user
# (idempotent — matches the lines whether commented or already set), restart gdm.
remote_script=$(cat <<REMOTE
echo "$PASSWORD" | sudo -S -p "" cp -n /etc/gdm3/daemon.conf /etc/gdm3/daemon.conf.bak
sudo sed -i \
  -e "s/^#\?[[:space:]]*AutomaticLoginEnable.*/AutomaticLoginEnable = true/" \
  -e "s/^#\?[[:space:]]*AutomaticLogin[[:space:]]*=.*/AutomaticLogin = $USER_NAME/" \
  /etc/gdm3/daemon.conf
sudo systemctl restart gdm
echo "autologin enabled for $USER_NAME; gdm restarted"
REMOTE
)

sshpass -p "$PASSWORD" ssh \
    -o StrictHostKeyChecking=accept-new \
    -o ConnectTimeout=10 \
    "$USER_NAME@$HOST" "$remote_script"
