import subprocess
import tempfile
from pathlib import Path

from web.vault import add_vault_entry, resolve_vault_entries_with_values
from web.mounts import list_remotes

# rclone's own three plain-English scope choices that actually make sense
# for this project -- the real list has five, but "Application Data Folder
# only" and "metadata only, no file contents" aren't useful for scanning
# wallet files, so they're left off rather than dumping all five raw rclone
# values on a user who's never seen this before.
SCOPE_CHOICES = [
    ("drive.readonly", "Read-only (recommended -- this app only ever needs to read your files)"),
    ("drive.file", "Files created by this app only"),
    ("drive", "Full access"),
]
DEFAULT_SCOPE = "drive.readonly"


def _vault_secret_name(remote_name):
    return f"rclone-{remote_name}-client-secret"


def _looks_like_google_client_id(client_id):
    """
    A real Google OAuth client ID always ends in this suffix -- catches
    the exact mistake confirmed live this session: a made-up value
    ("mathew.dostal-drive") typed into the Advanced field, which Google
    correctly (but confusingly, five minutes later, as a browser error
    page) rejects with "Error 401: invalid_client". Rejecting it here,
    before any subprocess call, turns that into an immediate, specific,
    in-app error instead.
    """
    return client_id.endswith(".apps.googleusercontent.com")


VERIFY_TIMEOUT_SECONDS = 30


def _cleanup_partial_remote(remote_name):
    subprocess.run(["rclone", "config", "delete", remote_name], capture_output=True, text=True)


def create_remote(remote_name, kind="gdrive", client_id="", client_secret="", scope=DEFAULT_SCOPE, progress_callback=None):
    """
    Runs `rclone config create` for a Google Drive (or GCS) remote, replacing
    the old "go run `rclone config` in a terminal yourself" instruction.

    No `--non-interactive` flag: per `rclone config create --help`, without
    it rclone takes the default for anything not passed as a key=value pair
    (e.g. `config_is_local` defaults to true) and, for an OAuth backend like
    Google Drive, that default IS "open a real local browser window and
    complete the OAuth handshake automatically" -- exactly what a desktop
    app sitting at a real machine with a real browser wants. This blocks
    until that finishes (or times out on rclone's own side), which is why
    the caller runs it as a background job.

    Critically, `rclone config create` writes the remote's config section
    to disk essentially immediately -- independent of whether the OAuth
    handshake that follows ever actually completes. Confirmed live this
    session: a failed or abandoned sign-in leaves a permanent, tokenless,
    non-functional remote sitting in rclone.conf, indistinguishable from a
    working one by exit code alone. This function verifies the remote
    actually works (a real read against it) before ever reporting success,
    and deletes the partial remote on any failure -- a failed attempt must
    never leave broken state behind.

    If a client_secret is given, it is routed through the vault (Portunus)
    exactly like every other secret this project handles -- written via
    `add_vault_entry` (temp file, never a CLI argument in this function's
    own call, never logged) and resolved back to a value only for the
    single `rclone config create` subprocess call below, never persisted by
    this project's own code. rclone's own config file (~/.config/rclone/
    rclone.conf) will still end up holding the resulting OAuth token --
    that's inherent to how every rclone remote works, not something this
    project's own storage choices control.

    :param remote_name: the rclone remote name, e.g. "gdrive".
    :param kind: "gdrive" or "gcs" -- selects the rclone backend type.
    :param client_id: optional -- blank uses rclone's own shared client id
        (the default, recommended path -- most people should never need
        to fill this in). If given, must look like a real Google OAuth
        client ID (ends in .apps.googleusercontent.com).
    :param client_secret: optional, paired with client_id.
    :param scope: one of SCOPE_CHOICES' keys.
    :param progress_callback: optional callable(current, total, message).
    :return: {"ok": bool, "report": str}
    """
    if progress_callback is None:
        progress_callback = lambda current, total, message="": None

    if client_id and not _looks_like_google_client_id(client_id):
        return {
            "ok": False,
            "report": (
                f"'{client_id}' doesn't look like a real Google OAuth client ID -- those always end in "
                "\".apps.googleusercontent.com\" (get the real value from Google Cloud Console). "
                "Leave this field blank to use the built-in default instead -- that's what most people want, "
                "and it works without any of this."
            ),
        }

    if remote_name in list_remotes():
        return {"ok": False, "report": f"A remote named '{remote_name}' already exists. Pick a different name, or remove it first from the Mounts page."}

    backend = "drive" if kind == "gdrive" else "google cloud storage"
    args = ["rclone", "config", "create", remote_name, backend]
    if kind == "gdrive":
        args += ["scope", scope]

    total_steps = 3
    resolved_secret = None
    if client_id and client_secret:
        total_steps = 4
        progress_callback(1, total_steps, "Storing your client secret in the vault")
        secret_name = _vault_secret_name(remote_name)
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(client_secret)
            secret_path = f.name
        try:
            add_vault_entry(secret_name, secret_path, description=f"rclone {kind} client secret for remote '{remote_name}'")
        finally:
            Path(secret_path).unlink(missing_ok=True)

        [(_, resolved_secret)] = resolve_vault_entries_with_values([secret_name])
        args += ["client_id", client_id, "client_secret", resolved_secret]

    progress_callback(total_steps - 1, total_steps, "Opening your browser to sign in to Google -- approve access there, this will finish automatically")
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        _cleanup_partial_remote(remote_name)
        return {"ok": False, "report": "Timed out waiting for the Google sign-in to complete (5 minutes). Nothing was saved -- try again from the Mounts page."}
    finally:
        resolved_secret = None  # best-effort scrub of the one local reference to the raw value

    if result.returncode != 0:
        _cleanup_partial_remote(remote_name)
        return {"ok": False, "report": f"rclone could not create the remote:\n{result.stderr.strip() or result.stdout.strip()}"}

    progress_callback(total_steps, total_steps, "Verifying the connection actually works")
    verify = subprocess.run(["rclone", "lsd", f"{remote_name}:", "--max-depth", "1"], capture_output=True, text=True, timeout=VERIFY_TIMEOUT_SECONDS)
    if verify.returncode != 0:
        _cleanup_partial_remote(remote_name)
        return {
            "ok": False,
            "report": (
                f"'{remote_name}' didn't actually finish signing in -- rclone couldn't read anything from it just now. "
                f"Nothing was saved; try again from the Mounts page.\n{verify.stderr.strip() or verify.stdout.strip()}"
            ),
        }

    progress_callback(total_steps, total_steps, "Done")
    return {"ok": True, "report": f"Connected -- '{remote_name}' is ready. Head to the Mounts page to attach and scan it."}


def _rclone_config_file_path():
    """
    Asks rclone itself where its config file lives (`rclone config file`)
    instead of hardcoding ~/.config/rclone/rclone.conf -- respects
    RCLONE_CONFIG/XDG_CONFIG_HOME the same way rclone's own commands do.
    This is the only reliable way to find the exact file
    update_remote_credentials() must snapshot before risking a partial
    rewrite of an already-working remote.

    :return: the config file path as a string, or None if it couldn't be
        determined -- update_remote_credentials() then skips its
        backup/restore safety net entirely rather than guessing a path.
    """
    result = subprocess.run(["rclone", "config", "file"], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines[-1] if lines else None


def _restore_config_backup(config_path, backup_content):
    """
    Rewrites rclone's config file back to its exact pre-update content --
    the rollback update_remote_credentials() runs on any failure. A
    full-file restore (not a second `rclone config update` back to the
    old values) is used deliberately: it's the only way to also correctly
    restore (or remove) any OAuth token rclone rewrote mid-attempt, which
    a value-by-value update back could not safely reconstruct. A no-op if
    no backup was ever captured (config_path/backup_content is None).
    """
    if config_path and backup_content is not None:
        Path(config_path).write_text(backup_content)


def update_remote_credentials(remote_name, client_id, client_secret, progress_callback=None):
    """
    Attaches (or replaces) a dedicated Google OAuth client on a remote that
    already exists, via `rclone config update` -- never delete-and-recreate,
    so the remote's name and anything already bound to it (mount history,
    scan targets) survive. This is the fix for the actual root cause
    documented in web/mounts.py's mount() docstring: a remote with no
    client_id authenticates through rclone's shared default Google API
    client, whose request quota is global across every rclone user on
    earth -- the confirmed cause of the mount dying every 20-30 minutes
    under sustained scan load.

    Unlike create_remote(), client_id and client_secret are both required
    here -- there's no "leave it blank for the default" option, since the
    whole point of calling this is to move a remote OFF the default shared
    client. Validation (_looks_like_google_client_id) and the vault-backed
    secret handling exactly mirror create_remote()'s.

    Per `rclone config update --help`, updating a remote's client_id/
    client_secret also refreshes its OAuth token -- there is no separate
    "re-auth" step to wire up here; the single `rclone config update` call
    below opens the browser and completes it, same as `rclone config
    create` does for a brand-new remote.

    Before touching anything, this snapshots rclone's whole config file
    (see _rclone_config_file_path()/_restore_config_backup()). If the
    update command fails, or the post-update verification read (`rclone
    lsd`, the same pattern create_remote() uses) fails, the snapshot is
    written straight back -- restoring the remote to its exact prior
    working state. This is deliberately NOT create_remote()'s
    delete-on-failure cleanup: that function is cleaning up a just-
    created, not-yet-trusted remote; this one is one bad credential
    update away from destroying a remote that was already working, so a
    failure here must never delete or rename it.

    :param remote_name: an existing rclone remote name (see list_remotes()).
    :param client_id: required -- must look like a real Google OAuth
        client ID (ends in .apps.googleusercontent.com).
    :param client_secret: required, paired with client_id.
    :param progress_callback: optional callable(current, total, message).
    :return: {"ok": bool, "report": str}
    """
    if progress_callback is None:
        progress_callback = lambda current, total, message="": None

    if not client_id or not _looks_like_google_client_id(client_id):
        return {
            "ok": False,
            "report": (
                f"'{client_id}' doesn't look like a real Google OAuth client ID -- those always end in "
                "\".apps.googleusercontent.com\" (get the real value from Google Cloud Console's OAuth "
                "client detail page)."
            ),
        }

    if not client_secret:
        return {
            "ok": False,
            "report": "Enter the client secret Google Cloud Console shows next to this client ID -- both are required together.",
        }

    if remote_name not in list_remotes():
        return {"ok": False, "report": f"No remote named '{remote_name}' exists yet -- connect it first from the Mounts page."}

    total_steps = 4
    progress_callback(1, total_steps, "Backing up the current configuration")
    config_path = _rclone_config_file_path()
    backup_content = None
    if config_path and Path(config_path).exists():
        backup_content = Path(config_path).read_text()

    progress_callback(2, total_steps, "Storing your client secret in the vault")
    secret_name = _vault_secret_name(remote_name)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(client_secret)
        secret_path = f.name
    try:
        add_vault_entry(secret_name, secret_path, description=f"rclone client secret for remote '{remote_name}'")
    finally:
        Path(secret_path).unlink(missing_ok=True)

    [(_, resolved_secret)] = resolve_vault_entries_with_values([secret_name])

    progress_callback(
        3, total_steps,
        "Updating the remote and re-authenticating with Google -- approve access there, this will finish automatically",
    )
    try:
        result = subprocess.run(
            ["rclone", "config", "update", remote_name, "client_id", client_id, "client_secret", resolved_secret],
            capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        _restore_config_backup(config_path, backup_content)
        return {
            "ok": False,
            "report": f"Timed out waiting for the Google sign-in to complete (5 minutes). '{remote_name}' was left unchanged -- try again from the Mounts page.",
        }
    finally:
        resolved_secret = None  # best-effort scrub of the one local reference to the raw value

    if result.returncode != 0:
        _restore_config_backup(config_path, backup_content)
        return {
            "ok": False,
            "report": f"rclone could not update '{remote_name}':\n{result.stderr.strip() or result.stdout.strip()}\n'{remote_name}' was left unchanged.",
        }

    progress_callback(total_steps, total_steps, "Verifying the connection actually works")
    verify = subprocess.run(["rclone", "lsd", f"{remote_name}:", "--max-depth", "1"], capture_output=True, text=True, timeout=VERIFY_TIMEOUT_SECONDS)
    if verify.returncode != 0:
        _restore_config_backup(config_path, backup_content)
        return {
            "ok": False,
            "report": (
                f"'{remote_name}' didn't finish signing in with the new client -- rclone couldn't read anything from it just now. "
                f"'{remote_name}' was restored to its previous working state; try again from the Mounts page.\n"
                f"{verify.stderr.strip() or verify.stdout.strip()}"
            ),
        }

    progress_callback(total_steps, total_steps, "Done")
    return {
        "ok": True,
        "report": f"'{remote_name}' now uses your dedicated Google OAuth client. Head to the Mounts page to reattach and scan it.",
    }
