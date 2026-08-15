#!/usr/bin/env bash
# One-shot setup for a git-cloned checkout of coin-finder: creates a local
# venv and installs requirements.txt into it. Deliberately does NOT curl
# this from the network and pipe it into bash -- this tool handles private
# keys, so the same "read the source before you run it" discipline the
# README asks of every third-party wallet tool applies to this script too.
# Run it from the repo root: ./scripts/install.sh
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required. Install it, then re-run this script." >&2
  exit 1
fi

PYTHON_VERSION="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PYTHON_MAJOR="$(echo "$PYTHON_VERSION" | cut -d. -f1)"
PYTHON_MINOR="$(echo "$PYTHON_VERSION" | cut -d. -f2)"
if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 9 ]; }; then
  echo "python3 >= 3.9 is required (found $PYTHON_VERSION)." >&2
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment at .venv ..."
  python3 -m venv .venv
fi

echo "Installing requirements.txt into .venv ..."
.venv/bin/pip install --upgrade pip >/dev/null
.venv/bin/pip install -r requirements.txt

cat <<'EOF'

============================================================
Installed.
============================================================
Run the app:
  source .venv/bin/activate
  python web/app.py

Then open http://127.0.0.1:5050

Optional, only if you need them (each is its own opt-in step, not run
automatically -- read them first):
  scripts/install_btcrecover.sh          -- wallet password recovery (unlock)
  scripts/install_exodus_tools.sh        -- Exodus seed.seco password recovery
  scripts/install_rclone.sh              -- mount Google Drive/GCS as a local drive
  pip install -r requirements-vault.txt  -- real Portunus-backed password vault

To keep the app itself up to date later, use the "Update" page in the app
(or `git pull` from the repo root).
EOF
