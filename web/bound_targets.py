import json
import os
import sys
import time
from pathlib import Path

from web.paths import app_data_dir

DEFAULT_STORE_PATH = app_data_dir() / "bound_targets.json"
VOLUMES_ROOT = "/Volumes"

# Common macOS boot-volume names -- excluded from list_mounted_volumes() so
# the "attach a drive" flow only ever surfaces volumes actually worth
# scanning (an old backup drive, a mounted image), not the machine's own
# system disk.
BOOT_VOLUME_NAMES = {"Macintosh HD", "Macintosh HD - Data"}


def _load(store_path):
    store_path = Path(store_path)
    if not store_path.exists():
        return []
    with open(store_path, "r") as f:
        return json.load(f)


def _save(store_path, targets):
    store_path = Path(store_path)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    with open(store_path, "w") as f:
        json.dump(targets, f, indent=2)


def list_targets(store_path=DEFAULT_STORE_PATH):
    """:return: [{"label", "path", "kind", "added_at"}, ...], insertion order."""
    return _load(store_path)


def add_target(label, path, kind, store_path=DEFAULT_STORE_PATH):
    """
    Adds a scan target reference to the store. `kind` is informational only
    ("local" | "volume" | "gdrive-mount" | "gcs-mount") -- scanning never
    branches on it, every kind is just a filesystem path once bound.
    """
    targets = _load(store_path)
    targets.append({"label": label, "path": path, "kind": kind, "added_at": time.time()})
    _save(store_path, targets)


def remove_target(label, store_path=DEFAULT_STORE_PATH):
    """
    Removes a target's saved reference only -- never touches the
    underlying path/files/volume. This must stay structurally impossible to
    misuse as "delete this drive's data": it only ever rewrites this
    project's own small local JSON file.
    """
    targets = _load(store_path)
    targets = [t for t in targets if t["label"] != label]
    _save(store_path, targets)


def list_mounted_volumes(store_path=DEFAULT_STORE_PATH):
    """
    Detects currently-mounted volumes worth offering as scan targets.
    macOS-only (enumerates /Volumes) -- returns an empty list with no error
    on other platforms, a stated limitation rather than a silent one.

    :return: [{"name", "path", "is_bound"}, ...]
    """
    if sys.platform != "darwin":
        return []

    bound_paths = {t["path"] for t in _load(store_path)}

    try:
        names = os.listdir(VOLUMES_ROOT)
    except OSError:
        return []

    volumes = []
    for name in sorted(names):
        if name in BOOT_VOLUME_NAMES:
            continue
        path = os.path.join(VOLUMES_ROOT, name)
        volumes.append({"name": name, "path": path, "is_bound": path in bound_paths})

    return volumes
