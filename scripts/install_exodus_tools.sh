#!/usr/bin/env bash
# Installs the tools needed to test candidate passwords against an Exodus
# desktop wallet's seed.seco file: hashcat itself (a real, well-audited
# password-recovery tool -- not something this project reimplements) and
# hashcat's own official exodus2hashcat.py extraction script (MIT licensed,
# from the hashcat project). Neither is committed to this repo's git
# history -- see .gitignore.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="$REPO_ROOT/vendor/hashcat-tools"
EXODUS2HASHCAT_URL="https://raw.githubusercontent.com/hashcat/hashcat/master/tools/exodus2hashcat.py"

mkdir -p "$VENDOR_DIR"

echo "Fetching hashcat's official exodus2hashcat.py..."
curl -fsSL "$EXODUS2HASHCAT_URL" -o "$VENDOR_DIR/exodus2hashcat.py"

if command -v hashcat >/dev/null 2>&1; then
  echo "hashcat already installed ($(hashcat --version))."
else
  if [[ "$(uname -s)" == "Darwin" ]]; then
    echo "Installing hashcat via Homebrew..."
    brew install hashcat
  else
    echo "hashcat not found and this script only auto-installs it on macOS."
    echo "Install it manually for your platform: https://hashcat.net/hashcat/"
  fi
fi

echo "Done. exodus2hashcat.py installed at vendor/hashcat-tools/."
echo "Testing candidate passwords against a real Exodus wallet must happen offline -- see README.md."
