import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from web.paths import app_data_dir

DEFAULT_STATE_PATH = app_data_dir() / "mounts_state.json"


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


def is_rclone_installed():
    return shutil.which("rclone") is not None


def install_rclone(progress_callback=None):
    """
    Installs rclone + macFUSE via Homebrew, driven entirely from the app --
    a packaged, click-to-run app's users must never be told to open a
    terminal and run a shell script. `scripts/install_rclone.sh` remains
    for the git-clone/developer path (documented in the README); this is
    the same two commands, run directly so the web UI can show real
    progress and a real pass/fail result instead of "go run this
    yourself."

    Requires Homebrew itself to already be present -- bootstrapping
    Homebrew from a packaged app is out of scope here (a stated limitation,
    not a silent one); that belongs to the eventual native packaging step
    (Tauri/installer), which can bundle or install Homebrew as part of
    first-run setup.

    macFUSE's own OS-level security approval (System Settings -> Privacy &
    Security, often a restart) still cannot be automated by anything --
    that limitation is inherent to macOS, not to how this is invoked.

    :param progress_callback: optional callable(current, total, message).
    :return: {"ok": bool, "report": str}
    """
    if progress_callback is None:
        progress_callback = lambda current, total, message="": None

    if shutil.which("brew") is None:
        return {
            "ok": False,
            "report": "Homebrew is required and wasn't found. Install it from https://brew.sh first, then try again.",
        }

    steps = [
        ("Installing rclone", ["brew", "install", "rclone"]),
        ("Installing macFUSE", ["brew", "install", "--cask", "macfuse"]),
    ]

    lines = []
    ok = True
    for i, (label, command) in enumerate(steps, start=1):
        progress_callback(i, len(steps), label)
        result = subprocess.run(command, capture_output=True, text=True)
        lines.append(f"## {label}")
        lines.append(result.stdout.strip())
        if result.stderr.strip():
            lines.append(result.stderr.strip())
        if result.returncode != 0:
            ok = False
            lines.append(f"FAILED (exit code {result.returncode})")
            break

    if ok:
        lines.append(
            "\nIMPORTANT: macOS will likely show a security prompt (System Settings -> "
            "Privacy & Security) asking you to approve the macFUSE system extension -- "
            "this cannot be automated. Approve it there (and restart if macOS asks you "
            "to) before mounting will actually work."
        )

    return {"ok": ok, "report": "\n".join(lines)}


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


def remote_status(remote_name):
    """
    A FAST, LOCAL signal (parses `rclone config show <name>` -- a config-
    file read, no network call) for whether a remote actually finished
    setting up. Confirmed live this session: `rclone config create` writes
    a remote's config section to disk before OAuth completes, so a failed
    or abandoned sign-in leaves a real, listed remote with no `token`
    field -- exactly what this distinguishes. NOT live proof the token
    still works (a revoked token would still read "connected" here) --
    that real verification belongs to create_remote()'s own creation-time
    check (web/rclone_wizard.py), not a per-page-load network call. This
    app already has one documented bug class (v0.32.2, v0.38.1) from
    exactly that mistake with a different slow subprocess (Portunus) --
    deliberately not repeating it here with a different tool.

    :return: "connected" | "incomplete"
    """
    result = subprocess.run(["rclone", "config", "show", remote_name], capture_output=True, text=True)
    if result.returncode != 0:
        return "incomplete"
    return "connected" if "token" in result.stdout else "incomplete"


def remove_remote(remote_name, state_path=DEFAULT_STATE_PATH):
    """
    Deletes a configured rclone remote entirely -- the recovery path this
    session's live bug was missing (two broken, tokenless remotes existed
    with zero way to remove or retry them from the UI). Unmounts first if
    currently mounted -- deleting a remote out from under a live FUSE
    mount would leave that mount silently broken rather than cleanly gone.
    """
    if is_mounted(remote_name, state_path=state_path):
        unmount(remote_name, state_path=state_path)
    subprocess.run(["rclone", "config", "delete", remote_name], capture_output=True, text=True)


def mount(remote_name, mount_point, state_path=DEFAULT_STATE_PATH, log_dir=None):
    """
    Starts `rclone nfsmount <remote>: <mount_point>` as a background
    process. NOT `rclone mount` -- confirmed live (direct reproduction,
    plus rclone's own Homebrew caveat) that Homebrew's macOS rclone build
    does not support the `mount` subcommand at all (no FUSE support
    included); `nfsmount` is the documented, working alternative and
    needs no macFUSE/system-extension approval. Always --read-only --
    this app only ever scans, never writes to Drive/GCS; a read-only
    mount makes "accidentally modify the user's real cloud storage"
    structurally impossible, not just a convention.

    stderr is captured to a real log file (not discarded) -- confirmed
    live this was the difference between a bare, undiagnosable "ERROR"
    pill and an actionable error message.
    """
    os.makedirs(mount_point, exist_ok=True)
    log_dir = Path(log_dir) if log_dir is not None else app_data_dir() / "mount-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{remote_name}.log"
    log_file = open(log_path, "w")
    process = subprocess.Popen(
        ["rclone", "nfsmount", f"{remote_name}:", str(mount_point), "--read-only", "--vfs-cache-mode", "minimal"],
        stdout=subprocess.DEVNULL,
        stderr=log_file,
    )

    state = _load_state(state_path)
    state[remote_name] = {"pid": process.pid, "mount_point": str(mount_point), "started_at": time.time(), "log_path": str(log_path)}
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
    """:return: [{"remote_name", "mount_point", "started_at", "is_mounted", "log_path"}, ...]"""
    state = _load_state(state_path)
    return [
        {
            "remote_name": name,
            "mount_point": entry["mount_point"],
            "started_at": entry["started_at"],
            "is_mounted": is_mounted(name, state_path=state_path),
            # .get(), not [] -- a mount started before this field existed
            # (mounts_state.json predates this fix) must not crash here.
            "log_path": entry.get("log_path"),
        }
        for name, entry in state.items()
    ]
