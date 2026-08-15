#!/bin/sh
# Stub "sidecar" executable registered with Tauri's externalBin mechanism.
#
# WHY THIS FILE EXISTS (the onedir-vs-externalBin integration problem):
# -----------------------------------------------------------------------
# Tauri's `bundle.externalBin` mechanism expects exactly ONE FILE per
# target-triple -- there is no supported way to register a *directory* of
# files as a sidecar. But this project's PyInstaller build is `--onedir`
# (see packaging/pyinstaller/coin_finder_ui.spec's docstring: a onedir
# build's reported pid IS the real Flask process, so a plain kill() on
# quit reliably frees the port -- a onefile build's bootloader-vs-child
# pid split does not have that guarantee). A onedir build is a
# *directory*: the real executable (`coin-finder-onedir`) plus a sibling
# `_internal/` directory it loads relative to its own on-disk location.
#
# THE RESOLUTION: bundle the *directory* via `bundle.resources` instead
# (which does support directories, landing under the .app's
# `Contents/Resources/`), and register THIS tiny shell-script stub -- not
# the real onedir binary -- as the `externalBin` sidecar. Tauri copies
# this stub into `Contents/MacOS/` next to the main app binary. When the
# Rust side spawns it as a sidecar, it locates the real onedir executable
# in `Contents/Resources/` (a fixed sibling of `Contents/MacOS/` in every
# macOS .app bundle) and `exec`s it, passing through all args.
#
# `exec` (not a plain subshell call) is deliberate and load-bearing: it
# replaces THIS PROCESS's image in place rather than forking a child, so
# the pid the OS reports for "the stub" and for "the real Flask process"
# are the SAME pid throughout the process's life -- preserving onedir's
# whole reason for being chosen: Tauri's CommandChild::kill() lands on the
# real Flask/Werkzeug process directly, no bootloader-vs-child indirection
# to go wrong.
#
# Path resolution handles both the built .app bundle layout and `tauri
# dev` (where externalBin binaries run from src-tauri/binaries/ directly
# and resources stay under src-tauri/resources/), so this one stub works
# unmodified in both.

set -e

STUB_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# 1. Built .app bundle: Contents/MacOS/<stub> -> Contents/Resources/coin-finder-onedir/coin-finder-onedir
BUNDLED="$STUB_DIR/../Resources/coin-finder-onedir/coin-finder-onedir"

# 2. `tauri dev`: src-tauri/binaries/<stub> -> src-tauri/resources/coin-finder-onedir/coin-finder-onedir
DEV="$STUB_DIR/../resources/coin-finder-onedir/coin-finder-onedir"

if [ -x "$BUNDLED" ]; then
    REAL_BIN="$BUNDLED"
elif [ -x "$DEV" ]; then
    REAL_BIN="$DEV"
else
    echo "coin-finder-sidecar-stub: could not locate the real coin-finder-onedir executable" >&2
    echo "  tried: $BUNDLED" >&2
    echo "  tried: $DEV" >&2
    exit 1
fi

exec "$REAL_BIN" "$@"
