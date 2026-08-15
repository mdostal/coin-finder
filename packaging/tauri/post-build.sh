#!/bin/sh
# Ad-hoc codesign step for the Tauri macOS `.app` bundle, run AFTER `tauri
# build` (there is no `afterBuildCommand` hook that fires late enough to
# have a real .app to sign, so this is a separate script run after).
#
# WHY THIS EXISTS, AND WHY IT DOES NOT (BY ITSELF) FIX GATEKEEPER:
# -----------------------------------------------------------------------
# An unsigned `tauri build` produces an .app with a technically-broken
# default ad-hoc signature (`codesign --verify` fails: "code has no
# resources but signature indicates they must be present"). Running
# `codesign --force --deep -s -` here produces a genuinely valid ad-hoc
# signature (verify passes afterward) -- but this does NOT restore a
# Gatekeeper bypass for a quarantined (downloaded/AirDropped) copy. A
# quarantined copy still shows a hard "'Coin Finder' is damaged and can't
# be opened. You should move it to the Trash" dialog, with no
# right-click-Open option. This is confirmed behavior on this author's
# other Tauri app (cleanup-tools), same toolchain/macOS version.
#
# The only thing that actually works for a personal install:
#   xattr -d com.apple.quarantine "Coin Finder.app"   # or the .dmg
# See README.md's desktop app section for the full explanation. This
# script still runs ad-hoc codesign anyway because it's free and produces
# a technically valid signature, even though it doesn't solve Gatekeeper
# on its own.
#
# Usage: run after `npm run tauri build` (or `npx tauri build`), from
# anywhere -- paths below are relative to this script's own location.
#   npm run tauri:build

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
BUNDLE_ROOT="$REPO_ROOT/src-tauri/target"

APPS=$(find "$BUNDLE_ROOT" -type d -name "*.app" -path "*/bundle/macos/*" 2>/dev/null || true)

if [ -z "$APPS" ]; then
    echo "post-build.sh: no .app bundle found under $BUNDLE_ROOT -- did \`tauri build\` run first?" >&2
    exit 1
fi

echo "$APPS" | while IFS= read -r app; do
    [ -z "$app" ] && continue
    echo "post-build.sh: ad-hoc signing $app"
    codesign --force --deep -s - "$app"

    if codesign --verify --deep --strict "$app" 2>&1; then
        echo "post-build.sh: codesign --verify passed for $app"
    else
        echo "post-build.sh: WARNING -- codesign --verify still failing for $app" >&2
    fi

    echo "post-build.sh: reminder -- ad-hoc signing does NOT bypass Gatekeeper for a" \
         "quarantined copy. See README.md for the real fix (xattr -d com.apple.quarantine)."
done
