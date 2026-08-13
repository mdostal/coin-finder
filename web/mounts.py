import json
import os
import subprocess
import time
from pathlib import Path

DEFAULT_STATE_PATH = Path(__file__).resolve().parent / "mounts_state.json"


def _load_state(state_path):
    state_path = Path(state_path)
    if not state_path.exists():
        return {}
    with open(state_path, "r") as f:
        return json.load(f)


def _save_state(state_path, state):
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def list_remotes():
    """
    :return: configured rclone remote names (via `rclone listremotes`), or
        an empty list if rclone isn't installed/configured yet -- never
        raises, since "not set up yet" is an expected state this app must
        handle gracefully (it's the whole reason the setup wizard exists).
    """
    try:
        result = subprocess.run(["rclone", "listremotes"], capture_output=True, text=True)
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []
    return [line.strip().rstrip(":") for line in result.stdout.splitlines() if line.strip()]


def mount(remote_name, mount_point, state_path=DEFAULT_STATE_PATH):
    """
    Starts `rclone mount <remote>: <mount_point>` as a background process.
    Always --read-only -- this app only ever scans, never writes to
    Drive/GCS; a read-only mount makes "accidentally modify the user's real
    cloud storage" structurally impossible, not just a convention.
    """
    os.makedirs(mount_point, exist_ok=True)
    process = subprocess.Popen(
        ["rclone", "mount", f"{remote_name}:", str(mount_point), "--read-only", "--vfs-cache-mode", "minimal"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    state = _load_state(state_path)
    state[remote_name] = {"pid": process.pid, "mount_point": str(mount_point), "started_at": time.time()}
    _save_state(state_path, state)


def unmount(remote_name, state_path=DEFAULT_STATE_PATH):
    """Unmounts and drops the tracked state entry. A no-op for an untracked remote."""
    state = _load_state(state_path)
    entry = state.get(remote_name)
    if entry is None:
        return

    subprocess.run(["umount", entry["mount_point"]], capture_output=True)
    del state[remote_name]
    _save_state(state_path, state)


def is_mounted(remote_name, state_path=DEFAULT_STATE_PATH):
    """
    True only if the tracked process is still alive AND the mount point is
    actually readable -- not just "does the path exist." A crashed FUSE
    mount is a known failure mode that leaves a path that looks fine but
    silently reads as permanently empty; a scan against a dead mount must
    never be allowed to look identical to a scan of a genuinely empty
    drive.
    """
    state = _load_state(state_path)
    entry = state.get(remote_name)
    if entry is None:
        return False

    try:
        os.kill(entry["pid"], 0)  # signal 0: probe existence only, never kills
    except OSError:
        return False

    try:
        os.listdir(entry["mount_point"])
    except OSError:
        return False

    return True


def list_mounts(state_path=DEFAULT_STATE_PATH):
    """:return: [{"remote_name", "mount_point", "started_at", "is_mounted"}, ...]"""
    state = _load_state(state_path)
    return [
        {
            "remote_name": name,
            "mount_point": entry["mount_point"],
            "started_at": entry["started_at"],
            "is_mounted": is_mounted(name, state_path=state_path),
        }
        for name, entry in state.items()
    ]
