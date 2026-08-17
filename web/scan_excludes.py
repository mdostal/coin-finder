import json
import time
from pathlib import Path

from web.paths import app_data_dir

DEFAULT_STORE_PATH = app_data_dir() / "scan_excludes.json"


def _load(store_path):
    store_path = Path(store_path)
    if not store_path.exists():
        return []
    with open(store_path, "r") as f:
        return json.load(f)


def _save(store_path, excludes):
    store_path = Path(store_path)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    with open(store_path, "w") as f:
        json.dump(excludes, f, indent=2)


def list_excludes(store_path=DEFAULT_STORE_PATH):
    """
    :return: [{"path", "added_at"}, ...], insertion order.

    User-configurable, not a built-in blocklist -- a fresh install starts
    with zero excludes. What's worth excluding (old junk paths, a
    known-empty Windows install, wherever things got hidden years ago) is
    something only the user actually knows, not something this project
    should guess at.
    """
    return _load(store_path)


def add_exclude(path, store_path=DEFAULT_STORE_PATH):
    excludes = _load(store_path)
    if any(e["path"] == path for e in excludes):
        return
    excludes.append({"path": path, "added_at": time.time()})
    _save(store_path, excludes)


def remove_exclude(path, store_path=DEFAULT_STORE_PATH):
    excludes = _load(store_path)
    excludes = [e for e in excludes if e["path"] != path]
    _save(store_path, excludes)
