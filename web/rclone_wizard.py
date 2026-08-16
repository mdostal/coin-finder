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
    :param client_id: optional -- blank uses rclone's own shared client id.
    :param client_secret: optional, paired with client_id.
    :param scope: one of SCOPE_CHOICES' keys.
    :param progress_callback: optional callable(current, total, message).
    :return: {"ok": bool, "report": str}
    """
    if progress_callback is None:
        progress_callback = lambda current, total, message="": None

    if remote_name in list_remotes():
        return {"ok": False, "report": f"A remote named '{remote_name}' already exists. Pick a different name, or remove it first from the Mounts page."}

    backend = "drive" if kind == "gdrive" else "google cloud storage"
    args = ["rclone", "config", "create", remote_name, backend]
    if kind == "gdrive":
        args += ["scope", scope]

    resolved_secret = None
    if client_id and client_secret:
        progress_callback(1, 3, "Storing your client secret in the vault")
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

    progress_callback(2, 3, "Opening your browser to sign in to Google -- approve access there, this will finish automatically")
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return {"ok": False, "report": "Timed out waiting for the Google sign-in to complete (5 minutes). Nothing was saved -- try again from the Mounts page."}
    finally:
        resolved_secret = None  # best-effort scrub of the one local reference to the raw value

    progress_callback(3, 3, "Done")

    if result.returncode != 0:
        return {"ok": False, "report": f"rclone could not create the remote:\n{result.stderr.strip() or result.stdout.strip()}"}

    return {"ok": True, "report": f"Connected -- '{remote_name}' is ready. Head to the Mounts page to attach and scan it."}
