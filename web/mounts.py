import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from web.paths import app_data_dir

DEFAULT_STATE_PATH = app_data_dir() / "mounts_state.json"

# A small sibling store, same JSON-file-keyed-by-remote-name shape as
# DEFAULT_STATE_PATH/mounts_state.json (deliberately not folded into that
# same file/dict -- mounts_state.json is churned on every mount/unmount and
# only ever holds currently-running-mount bookkeeping, while this holds a
# user's deliberate tuning choice that must persist across mounts/unmounts/
# restarts untouched).
DEFAULT_MOUNT_SETTINGS_PATH = app_data_dir() / "mount_settings.json"

# gmc-03: the exact values mount()'s argv hardcoded before per-remote tuning
# existed (see mount()'s own docstring for how 16/8 was arrived at live) --
# now the fallback for any remote that hasn't opted into custom settings, so
# adding this store is a no-op behavior change for every existing remote.
DEFAULT_CHECKERS = 16
DEFAULT_TPSLIMIT = 8


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


def _validate_positive_int(value, field_name):
    """
    Positive integers only, rejected here -- before this value can ever
    reach an rclone command line -- rather than left to rclone itself to
    reject (or silently misinterpret) a bad `--checkers`/`--tpslimit`
    argument. `int()` itself already refuses a non-numeric string (and a
    float-looking one like "1.5") by raising ValueError, so that check is
    free; zero/negative need an explicit check since `int()` accepts them.
    """
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a whole number, got {value!r}.")
    if parsed <= 0:
        raise ValueError(f"{field_name} must be a positive number, got {parsed}.")
    return parsed


def get_mount_settings(remote_name, settings_path=DEFAULT_MOUNT_SETTINGS_PATH):
    """
    Effective per-remote mount tuning -- {"checkers", "tpslimit"} -- falling
    back to DEFAULT_CHECKERS/DEFAULT_TPSLIMIT for any field (or the whole
    remote) that has no saved override. Never raises: a missing or
    unreadable-for-this-remote entry is exactly "use the defaults", not an
    error.
    """
    settings = _load_state(settings_path)
    entry = settings.get(remote_name, {})
    return {
        "checkers": entry.get("checkers", DEFAULT_CHECKERS),
        "tpslimit": entry.get("tpslimit", DEFAULT_TPSLIMIT),
    }


def save_mount_settings(remote_name, checkers, tpslimit, settings_path=DEFAULT_MOUNT_SETTINGS_PATH):
    """
    Validates and persists a per-remote checkers/tpslimit override. Raises
    ValueError (never reaches subprocess/rclone) for a negative, zero, or
    non-numeric value -- validation happens before _save_state is ever
    called, so an invalid submission never partially overwrites a
    previously-saved good value.

    :return: the validated {"checkers", "tpslimit"} that was saved.
    """
    checkers = _validate_positive_int(checkers, "checkers")
    tpslimit = _validate_positive_int(tpslimit, "tpslimit")

    settings = _load_state(settings_path)
    settings[remote_name] = {"checkers": checkers, "tpslimit": tpslimit}
    _save_state(settings_path, settings)
    return {"checkers": checkers, "tpslimit": tpslimit}


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


def mount(remote_name, mount_point, state_path=DEFAULT_STATE_PATH, log_dir=None, settings_path=DEFAULT_MOUNT_SETTINGS_PATH):
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

    --checkers/--tpslimit come from get_mount_settings(remote_name) --
    DEFAULT_CHECKERS (16) / DEFAULT_TPSLIMIT (8) below for any remote that
    hasn't saved its own values (gmc-03: a no-op behavior change for every
    remote that doesn't opt in). The numbers below explain why those two
    particular defaults were chosen, not why they're hardcoded -- they no
    longer are; a multi-terabyte drive that needs different tuning can get
    it from the settings form on /mounts without a code change.

    --checkers 16 (rclone's default is 8; this was 32 briefly, see below):
    a `find` scan over this mount is a pure metadata walk (readdir/stat,
    no file content), and the original default concurrency left a real
    6TB/many-hundred-thousand-file drive crawling for 10+ hours with a
    mostly-idle rclone process in between -- confirmed live via the
    mount's own log (zero errors, clean directory listings, just
    serialized on too few concurrent listing workers). --checkers 32
    then overshot the other way: confirmed live via the same log that
    this remote authenticates through rclone's own shared default Google
    API client (this remote's `client_id`/`client_secret` are blank),
    whose request quota is shared across every rclone user on Google
    Drive globally, not just this drive -- 32 concurrent listers against
    a big/deep tree burst past that shared quota (repeated real 403
    "Queries per minute" RATE_LIMIT_EXCEEDED errors, each one silently
    dropping an entire subtree's listing, not just slowing down). 16
    plus --tpslimit smooths the request rate instead of bursting-then-
    backing-off, which is faster in practice than either extreme. The
    durable fix is a personal Google Cloud OAuth client (its own
    dedicated quota) via create_remote()'s client_id/client_secret --
    this tuning is a mitigation, not a replacement for that.
    --tpslimit 8: caps total Drive API transactions/sec so the mount
    self-paces under the shared quota instead of relying purely on
    rclone's post-hoc 403 backoff.
    --drive-skip-dangling-shortcuts: this user's real Drive has a small
    number of broken shortcuts (files whose link target was deleted) that
    otherwise get silently re-resolved (and logged) on every directory
    cache refresh -- skip them outright since a dangling shortcut can
    never resolve to real wallet content anyway.
    """
    os.makedirs(mount_point, exist_ok=True)
    log_dir = Path(log_dir) if log_dir is not None else app_data_dir() / "mount-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{remote_name}.log"
    log_file = open(log_path, "w")
    settings = get_mount_settings(remote_name, settings_path=settings_path)
    process = subprocess.Popen(
        [
            "rclone", "nfsmount", f"{remote_name}:", str(mount_point),
            "--read-only",
            "--vfs-cache-mode", "minimal",
            "--checkers", str(settings["checkers"]),
            "--tpslimit", str(settings["tpslimit"]),
            "--drive-skip-dangling-shortcuts",
        ],
        stdout=subprocess.DEVNULL,
        stderr=log_file,
    )

    state = _load_state(state_path)
    state[remote_name] = {"pid": process.pid, "mount_point": str(mount_point), "started_at": time.time(), "log_path": str(log_path)}
    _save_state(state_path, state)


def _unmount_path(mount_point):
    """
    The actual diskutil-first-then-umount-fallback OS mechanics, factored
    out of unmount() so test_mount() can reuse it directly against a raw
    path -- test_mount()'s throwaway mount is never written to
    mounts_state.json (it's not a tracked, real mount), so it can't go
    through unmount()'s remote_name-keyed lookup; worse, calling
    unmount(remote_name) from test_mount() would risk tearing down a
    REAL, currently-tracked mount for that same remote if one happens to
    be active at the same time. Confirmed live: plain `umount` fails on
    this NFS-served mount with "Resource busy -- try 'diskutil unmount'"
    even when nothing is actually reading from it -- macOS's own error
    message names the real fix. `diskutil unmount` is tried first; a
    plain `umount` is the fallback for any platform where `diskutil`
    isn't on PATH.
    """
    result = subprocess.run(["diskutil", "unmount", str(mount_point)], capture_output=True)
    if result.returncode != 0:
        subprocess.run(["umount", str(mount_point)], capture_output=True)


def unmount(remote_name, state_path=DEFAULT_STATE_PATH):
    """
    Unmounts and drops the tracked state entry. A no-op for an untracked
    remote.
    """
    state = _load_state(state_path)
    entry = state.get(remote_name)
    if entry is None:
        return

    _unmount_path(entry["mount_point"])
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


DEFAULT_TEST_MOUNT_TIMEOUT_SECONDS = 30

# rclone nfsmount's Popen call returns immediately, well before the NFS
# mount is actually bound -- this is how long test_mount() waits before
# its first (and only) read attempt. Small relative to the overall
# timeout on purpose: the read itself is where the real, unbounded time
# should go, not this fixed startup grace.
_TEST_MOUNT_ATTACH_GRACE_SECONDS = 2


def _log_tail(log_path, lines=20):
    try:
        with open(log_path) as f:
            return "".join(f.readlines()[-lines:]).strip()
    except OSError:
        return ""


def test_mount(remote_name, timeout=DEFAULT_TEST_MOUNT_TIMEOUT_SECONDS, log_dir=None, settings_path=DEFAULT_MOUNT_SETTINGS_PATH):
    """
    A bounded, real "does this remote actually hold up" check the user
    can run any time, instead of the only prior option -- starting a real
    find/check-balances job and waiting to find out, which is how ~49
    manual reattach cycles got burned on the old shared-client mount (see
    web/mounts.py's mount() docstring for the root cause that fix
    addressed). Mounts remote_name to a THROWAWAY temp directory (never
    the caller's real, configured mount point for that remote -- a test
    must never collide with, or be confused with, a currently-bound real
    mount for the same remote), performs one real, bounded directory
    listing through that mount (not just an rclone exit-code check --
    rclone nfsmount can report success and still serve a wedged/broken
    filesystem), and ALWAYS unmounts and cleans up the temp directory
    again before returning, on every exit path.

    Hard-bounded on the whole cycle via `timeout`. The mount step itself
    is a non-blocking subprocess.Popen (same pattern as mount()), so it
    can't hang this function; the actual read is run as its own
    subprocess (`ls` against the mounted path) with subprocess.run's own
    `timeout=`, so if the FUSE mount is wedged, it's that read subprocess
    that hangs and gets killed when its timeout elapses -- never this
    function's own thread. This is deliberately NOT is_mounted()'s
    unbounded os.listdir() (web/mounts.py's own documented failure mode):
    a verification feature that can itself hang forever would defeat its
    own purpose.

    gmc-03: mounts with the same get_mount_settings(remote_name)
    checkers/tpslimit that a real mount() call would use -- a test that
    passed under the hardcoded defaults but the real mount then used a
    much more aggressive saved setting (or vice versa) would tell the user
    nothing about whether the setting they're actually about to run with
    holds up.

    :param remote_name: an existing rclone remote name (see list_remotes()).
    :param timeout: total seconds allowed for the whole mount-attach +
        read cycle before giving up and reporting a timeout failure.
    :param log_dir: where to write rclone's stderr for this test run
        (defaults to the same directory real mounts log to, but under a
        "-test.log" filename so a test run never clobbers a real,
        currently-active mount's own diagnostic log for the same remote).
    :param settings_path: where per-remote checkers/tpslimit overrides are
        read from (see get_mount_settings()) -- defaults to
        DEFAULT_MOUNT_SETTINGS_PATH, the same store a real mount() call
        reads from.
    :return: {"ok": bool, "report": str} -- report carries rclone's real
        error text on failure (never a generic message), or real success
        detail (what was actually listed) on success.
    """
    mount_point = Path(tempfile.mkdtemp(prefix=f"coin-finder-test-mount-{remote_name}-"))
    log_dir = Path(log_dir) if log_dir is not None else app_data_dir() / "mount-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{remote_name}-test.log"
    settings = get_mount_settings(remote_name, settings_path=settings_path)

    process = None
    log_file = open(log_path, "w")
    try:
        try:
            process = subprocess.Popen(
                [
                    "rclone", "nfsmount", f"{remote_name}:", str(mount_point),
                    "--read-only",
                    "--vfs-cache-mode", "minimal",
                    "--checkers", str(settings["checkers"]),
                    "--tpslimit", str(settings["tpslimit"]),
                ],
                stdout=subprocess.DEVNULL,
                stderr=log_file,
            )
        except FileNotFoundError:
            return {"ok": False, "report": "FAIL -- rclone isn't installed (or isn't on PATH) -- install it from the Mounts page first."}

        time.sleep(min(_TEST_MOUNT_ATTACH_GRACE_SECONDS, timeout))
        log_file.flush()

        if process.poll() is not None:
            # Exited already -- the mount attempt itself failed outright
            # (e.g. a bad/nonexistent remote name). rclone's real error
            # text lives in the log file this Popen call wrote to, never
            # discarded for a generic message.
            return {
                "ok": False,
                "report": f"FAIL -- rclone exited before '{remote_name}' finished mounting:\n{_log_tail(log_path)}",
            }

        remaining = max(timeout - _TEST_MOUNT_ATTACH_GRACE_SECONDS, 1)
        try:
            listing = subprocess.run(["ls", "-la", str(mount_point)], capture_output=True, text=True, timeout=remaining)
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "report": (
                    f"FAIL -- '{remote_name}' mounted, but reading its contents did not finish within {timeout}s -- "
                    "the mount may be wedged under load, the exact failure this test exists to catch."
                ),
            }

        if listing.returncode != 0:
            return {
                "ok": False,
                "report": f"FAIL -- '{remote_name}' mounted, but reading its contents failed:\n{listing.stderr.strip() or listing.stdout.strip()}",
            }

        entries = [line for line in listing.stdout.splitlines()[1:] if line.strip()]  # skip ls -la's leading "total N" line
        return {
            "ok": True,
            "report": f"PASS -- mounted '{remote_name}' and listed its contents successfully ({len(entries)} entr{'y' if len(entries) == 1 else 'ies'} at the top level).",
        }
    finally:
        log_file.close()
        _unmount_path(mount_point)
        if process is not None and process.poll() is None:
            process.terminate()
        shutil.rmtree(mount_point, ignore_errors=True)
