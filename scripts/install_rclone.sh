#!/usr/bin/env bash
# Installs rclone (mounts Google Drive/GCS buckets as local-looking
# directories, so multi-terabyte cloud storage doesn't need a full local
# download first) plus macFUSE (required by rclone mount on macOS).
set -euo pipefail

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required. Install it from https://brew.sh first." >&2
  exit 1
fi

echo "Installing rclone..."
brew install rclone

echo "Installing macFUSE (required for 'rclone mount' on macOS)..."
brew install --cask macfuse

cat <<'EOF'

============================================================
IMPORTANT: macFUSE requires manual approval -- this cannot be scripted.
============================================================
macOS will likely show a security prompt (System Settings -> Privacy &
Security) asking you to allow a system extension from "Benjamin Fleischer."
You must click Allow there, and may need to restart your Mac, before
`rclone mount` will actually work. Running this script again afterward will
not re-trigger that prompt if you already approved it.

Next steps:
  1. Approve the macFUSE extension in System Settings if prompted (and
     restart if macOS asks you to).
  2. Run `rclone config` to set up a Google Drive or GCS remote --
     this opens a browser for Google sign-in (Drive) or asks for a
     service-account key (GCS). See the coin-finder README's
     "Mounting Google Drive for Multi-Terabyte Drives" section, or use
     the /mounts page in the local web UI once a remote is configured.
============================================================
EOF
