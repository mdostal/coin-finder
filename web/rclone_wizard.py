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
