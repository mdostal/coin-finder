"""
Single fallback source of truth for the running version.

CHANGELOG.md's latest heading is still the real, primary source of truth
(see web/update.py's get_current_version()) -- but a frozen desktop build
doesn't ship CHANGELOG.md, so it had no way to report its own version at
all ("Couldn't determine the running version in this build"). This is a
plain importable module instead of a data file specifically so PyInstaller
bundles it automatically along with the rest of the source, no spec
changes needed.

Bump this alongside package.json / src-tauri/Cargo.toml /
src-tauri/tauri.conf.json / CHANGELOG.md's new heading at every release --
same manual version-bump routine, one more file.
"""

VERSION = "0.53.6"
