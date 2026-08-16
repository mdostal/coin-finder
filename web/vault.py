import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from dotenv import get_key, set_key

from web.paths import app_data_dir

PROJECT = "coin-finder"
GROUP = "coin-finder/candidates"

# Every `portunus` subprocess call below MUST pass both of these. Confirmed
# the hard way, live, against the real installed app: `portunus` inherits
# whatever stdin it's given, and a subprocess spawned from inside the
# Tauri-managed sidecar gets a piped (not terminal, not closed) stdin --
# nothing this project's own code does closes it. If portunus ever tries
# to read from stdin (its own prompt, unlock flow, anything), that read
# blocks forever on a pipe that will never produce EOF, freezing this
# single-threaded Flask server for every user, not just the one request.
# `stdin=DEVNULL` makes that read return EOF immediately instead of
# hanging; `timeout=` is the same defense-in-depth this project already
# requires of every `requests.*()` call (see services/__init__.py), here
# for the same reason: a call with no way to fail must not be allowed to
# hang forever either.
PORTUNUS_TIMEOUT_SECONDS = 15

# Fallback store used only when the `portunus` CLI isn't on PATH -- e.g. a
# fresh install that hasn't set it up yet. Deliberately dumb (plaintext
# local .env + a metadata sidecar): Portunus is the real vault; this exists
# so the app still works, not to replace it.
FALLBACK_ENV_PATH = app_data_dir() / "vault_fallback.env"
FALLBACK_META_PATH = app_data_dir() / "vault_fallback_meta.json"


def _portunus_available():
    return shutil.which("portunus") is not None


def list_vault_entries(include_revoked=False):
    """
    Metadata only -- name, description, tags, state, etc. -- never a
    secret value. Portunus's own `list` command is documented as
    metadata-only by design; this wrapper doesn't add that guarantee, it
    relies on it. Falls back to the local metadata sidecar if Portunus
    isn't installed.

    :return: [{"name", "description", "state", ...}, ...]
    """
    if not _portunus_available():
        return _list_vault_entries_fallback(include_revoked)

    try:
        result = subprocess.run(
            ["portunus", "list", "--project", PROJECT, "--json"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=PORTUNUS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return []
    if result.returncode != 0:
        return []

    entries = json.loads(result.stdout or "[]")
    if not include_revoked:
        entries = [e for e in entries if e.get("state") != "revoked"]
    return entries


def add_vault_entry(name, value_file_path, description="", sm_name=None):
    """
    Stores a candidate password/phrase into Portunus's local encrypted
    vault, reading the value from a local file (never a CLI argument) --
    the same file-only-secrets discipline this project uses everywhere.
    Lands as `dropped` then immediately `enabled` so it's usable right away.
    Falls back to the local .env store if Portunus isn't installed.

    :param name: short reference name, e.g. "password-1" -- this is what
        the rest of the app (and the user) refers to it by; the value
        itself is never handled by this project's own code after this call.
    :param value_file_path: local file containing the value.
    :param sm_name: vault key; defaults to an uppercased, underscored form
        of name if not given.
    """
    if not _portunus_available():
        _add_vault_entry_fallback(name, value_file_path, description)
        return

    sm_name = sm_name or name.upper().replace("-", "_")
    subprocess.run(
        [
            "portunus", "drop", name, sm_name,
            "--project", PROJECT,
            "--group", GROUP,
            "--description", description or name,
            "--value-file", str(value_file_path),
        ],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=PORTUNUS_TIMEOUT_SECONDS,
    )
    subprocess.run(
        ["portunus", "state", name, "enabled"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=PORTUNUS_TIMEOUT_SECONDS,
    )


def revoke_vault_entry(name):
    """Soft-deletes via Portunus's own lifecycle state, not a hard delete -- consistent with Portunus's own state model."""
    if not _portunus_available():
        _revoke_vault_entry_fallback(name)
        return
    subprocess.run(
        ["portunus", "state", name, "revoked"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=PORTUNUS_TIMEOUT_SECONDS,
    )


def edit_vault_entry(name, description):
    """
    Updates a saved entry's description via Portunus's own `retag` command
    -- metadata only, the underlying secret value is never re-touched
    (unlike a delete-and-re-add, this also preserves state/history).
    """
    if not _portunus_available():
        _edit_vault_entry_fallback(name, description)
        return
    subprocess.run(
        ["portunus", "retag", name, "--description", description],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=PORTUNUS_TIMEOUT_SECONDS,
    )


def resolve_vault_entries_with_values(names):
    """
    Resolves each named vault entry to its real value and returns them
    paired with their names. This is the only place raw values pass
    through this project's own memory, and only transiently -- callers
    use it to (a) build a candidates file and (b) match a found password
    back to the label that produced it, never to display or log the
    value itself.

    :return: [(name, value), ...]
    :raises RuntimeError: if any named entry fails to resolve.
    """
    if not _portunus_available():
        return _resolve_vault_entries_with_values_fallback(names)

    pairs = []
    for name in names:
        try:
            result = subprocess.run(
                ["portunus", "resolve", f"{{{{secret:{name}}}}}"],
                capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=PORTUNUS_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Could not resolve vault entry '{name}': portunus timed out after {PORTUNUS_TIMEOUT_SECONDS}s.")
        if result.returncode != 0:
            raise RuntimeError(f"Could not resolve vault entry '{name}': {result.stderr.strip()}")
        resolved_path = result.stdout.strip()
        with open(resolved_path, "r") as f:
            pairs.append((name, f.read().strip()))
    return pairs


def resolve_vault_entries_to_candidates_file(names):
    """
    Combines the resolved values of each named vault entry into one local
    candidates file, one value per line, matching the exact format
    unlock_wallet.py/unlock_exodus_wallet.py already expect.

    :return: path to a new local candidates file (caller is responsible
        for deleting it after use, same as every other candidates-file
        caller in this project).
    """
    pairs = resolve_vault_entries_with_values(names)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("\n".join(value for _, value in pairs))
        return f.name


def _fallback_key(name):
    return name.upper().replace("-", "_")


def _load_fallback_meta():
    if not FALLBACK_META_PATH.exists():
        return []
    return json.loads(FALLBACK_META_PATH.read_text())


def _save_fallback_meta(entries):
    FALLBACK_META_PATH.write_text(json.dumps(entries, indent=2))


def _list_vault_entries_fallback(include_revoked):
    entries = _load_fallback_meta()
    if not include_revoked:
        entries = [e for e in entries if e.get("state") != "revoked"]
    return entries


def _add_vault_entry_fallback(name, value_file_path, description):
    with open(value_file_path, "r") as f:
        value = f.read().strip()

    FALLBACK_ENV_PATH.touch(exist_ok=True)
    set_key(str(FALLBACK_ENV_PATH), _fallback_key(name), value, quote_mode="always")

    entries = [e for e in _load_fallback_meta() if e["name"] != name]
    entries.append({"name": name, "description": description or name, "state": "enabled"})
    _save_fallback_meta(entries)


def _revoke_vault_entry_fallback(name):
    entries = _load_fallback_meta()
    for entry in entries:
        if entry["name"] == name:
            entry["state"] = "revoked"
    _save_fallback_meta(entries)


def _edit_vault_entry_fallback(name, description):
    entries = _load_fallback_meta()
    for entry in entries:
        if entry["name"] == name:
            entry["description"] = description
    _save_fallback_meta(entries)


def _resolve_vault_entries_with_values_fallback(names):
    pairs = []
    for name in names:
        value = get_key(str(FALLBACK_ENV_PATH), _fallback_key(name))
        if value is None:
            raise RuntimeError(f"Could not resolve vault entry '{name}' from the local fallback store.")
        pairs.append((name, value))
    return pairs
