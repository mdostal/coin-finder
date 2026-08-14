import re
import subprocess
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"
RELEASES_API_URL = "https://api.github.com/repos/mdostal/coin-finder/releases/latest"

_VERSION_HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.MULTILINE)


def get_current_version(changelog_path=DEFAULT_CHANGELOG_PATH):
    """CHANGELOG.md is this project's only version record -- the first `## [X.Y.Z]` heading (skipping `## [Unreleased]`) is the running version."""
    text = Path(changelog_path).read_text()
    match = _VERSION_HEADING.search(text)
    return match.group(1) if match else None


def check_for_update(changelog_path=DEFAULT_CHANGELOG_PATH):
    """
    Compares the local version against the latest published GitHub release.
    Never raises -- a network hiccup just means "couldn't check," not a
    broken page.

    :return: {"current", "latest", "update_available"} plus "error" if the
        GitHub API call itself failed.
    """
    current = get_current_version(changelog_path)
    try:
        resp = requests.get(RELEASES_API_URL, timeout=10)
        latest = resp.json()["tag_name"].lstrip("v")
    except Exception as e:
        return {"current": current, "latest": None, "update_available": False, "error": str(e)}

    return {"current": current, "latest": latest, "update_available": latest != current}


def perform_update():
    """
    Updates the local checkout via `git fetch` + a fast-forward-only merge
    -- refuses (rather than clobbers) if the working tree has diverged or
    has local changes, instead of forcing anything. Does not restart the
    running app -- the caller is responsible for telling the user to do
    that themselves.

    :return: {"ok": bool, "output": str}
    """
    fetch = subprocess.run(["git", "fetch", "origin", "main"], cwd=REPO_ROOT, capture_output=True, text=True)
    if fetch.returncode != 0:
        return {"ok": False, "output": fetch.stdout + fetch.stderr}

    merge = subprocess.run(["git", "merge", "--ff-only", "origin/main"], cwd=REPO_ROOT, capture_output=True, text=True)
    return {"ok": merge.returncode == 0, "output": fetch.stdout + fetch.stderr + merge.stdout + merge.stderr}
