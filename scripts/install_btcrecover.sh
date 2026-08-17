#!/usr/bin/env bash
# Installs BTCRecover (3rdIteration/btcrecover -- the actively maintained
# Python 3 fork; the original gurnec/btcrecover is Python 2-only and does not
# run on Python 3) into vendor/btcrecover/. Not committed to this repo's git
# history -- see .gitignore.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="$REPO_ROOT/vendor/btcrecover"
BTCRECOVER_REMOTE="https://github.com/3rdIteration/btcrecover.git"

mkdir -p "$REPO_ROOT/vendor"

if [ -d "$VENDOR_DIR/.git" ]; then
  echo "vendor/btcrecover already present -- updating..."
  git -C "$VENDOR_DIR" pull --ff-only
else
  echo "Cloning BTCRecover into vendor/btcrecover..."
  git clone --depth 1 "$BTCRECOVER_REMOTE" "$VENDOR_DIR"
fi

if [ -f "$VENDOR_DIR/requirements.txt" ]; then
  echo "Installing BTCRecover's Python dependencies..."
  python3 -m pip install --quiet -r "$VENDOR_DIR/requirements.txt" || \
    echo "Warning: some BTCRecover dependencies failed to install (e.g. coincurve wheel unavailable for this Python version) -- BTCRecover falls back to its slower pure-Python backend and prints its own warning when run."
fi

echo "Done. BTCRecover installed at vendor/btcrecover/."
echo "Read vendor/btcrecover/SKILL.md before running any real wallet recovery -- it documents the required offline safety workflow."
