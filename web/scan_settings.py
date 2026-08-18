import json
import sqlite3
from pathlib import Path

from tools.check_wallet_balances import GLOBAL_MAX_WORKERS, PER_COIN_MAX_CONCURRENCY
from web.paths import app_data_dir

# Small key-value settings store, same pattern as web/auto_unlock_history.py
# and web/vault.py's own simplicity (see structured-outline.md #1.6) --
# not a new heavyweight config system.
DEFAULT_DB_PATH = app_data_dir() / "scan_settings.db"

VALID_MODES = ("auto", "custom")

# The full four-field profile from structured-outline.md #1.6 -- only the
# two check_balances-relevant fields are actually read by a job dispatch
# route yet (see web.app's _run_check_balances_job/
# _run_check_balances_selected_job); search_walk_threads/analyze_processes
# exist in the schema now so a later story (sse-06) doesn't need a schema
# migration to add them, but nothing reads them yet.
DEFAULT_OVERRIDES = {
    "search_walk_threads": None,
    "analyze_processes": None,
    "check_balances_global_workers": None,
    "check_balances_per_coin_concurrency": None,
}

_SCHEMA = "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"


def _connect(db_path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def get_settings(db_path=DEFAULT_DB_PATH):
    """
    :return: {"mode": "auto"|"custom", "overrides": {...}} -- overrides
        always contains every known key (see DEFAULT_OVERRIDES), even
        before any set_overrides() call, so callers never need to guard
        against a partially-populated dict. A db file that doesn't exist
        yet (nothing has ever been set) is treated as "auto mode, no
        overrides" without creating one -- a plain read must never itself
        leave a stray file on disk.
    """
    if not Path(db_path).exists():
        return {"mode": "auto", "overrides": dict(DEFAULT_OVERRIDES)}

    conn = _connect(db_path)
    try:
        rows = dict(conn.execute("SELECT key, value FROM settings").fetchall())
    finally:
        conn.close()

    mode = rows.get("mode", "auto")
    overrides = dict(DEFAULT_OVERRIDES)
    if "overrides" in rows:
        overrides.update(json.loads(rows["overrides"]))
    return {"mode": mode, "overrides": overrides}


def set_mode(mode, db_path=DEFAULT_DB_PATH):
    """
    :param mode: "auto" (default -- auto-detect resource use from machine
        specs at call time) or "custom" (use overrides, falling back to
        the auto-detected/tuned default for any field left null).
    """
    if mode not in VALID_MODES:
        raise ValueError(f"Invalid mode: {mode!r} (must be one of {VALID_MODES})")

    conn = _connect(db_path)
    try:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('mode', ?)", (mode,))
        conn.commit()
    finally:
        conn.close()


def set_overrides(overrides, db_path=DEFAULT_DB_PATH):
    """
    Merges the given keys into the stored overrides dict -- a partial
    update, so setting only check_balances_global_workers doesn't require
    also resending the other three fields. A value of None clears that
    field back to "use the auto-detected/tuned default". Unknown keys are
    rejected outright (rather than silently accepted) to catch a typo'd
    settings-route field name early instead of it silently doing nothing.
    """
    unknown = set(overrides) - set(DEFAULT_OVERRIDES)
    if unknown:
        raise ValueError(f"Unknown override key(s): {sorted(unknown)}")

    current = get_settings(db_path)["overrides"]
    current.update(overrides)

    conn = _connect(db_path)
    try:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('overrides', ?)", (json.dumps(current),))
        conn.commit()
    finally:
        conn.close()


def resolve_check_balances_workers(db_path=DEFAULT_DB_PATH):
    """
    The first (and, for now, only) settings consumer wired end-to-end --
    proves the plumbing works on the smallest possible slice before
    sse-06 generalizes it to search/analyze too.

    :return: (global_max_workers, per_coin_max_concurrency) -- the values
        the next check_balances job dispatch should use. "auto" mode (the
        default) always resolves to today's tuned constants (64, 15) --
        per structured-outline.md #1.6, these two are network-bound, not
        a function of local machine specs, so "auto" has nothing new to
        compute for them. A "custom" mode with a null override for a
        given field falls back to that same tuned default for just that
        field.
    """
    settings = get_settings(db_path)
    overrides = settings["overrides"] if settings["mode"] == "custom" else {}

    global_workers = overrides.get("check_balances_global_workers")
    per_coin = overrides.get("check_balances_per_coin_concurrency")
    return (
        global_workers if global_workers is not None else GLOBAL_MAX_WORKERS,
        per_coin if per_coin is not None else PER_COIN_MAX_CONCURRENCY,
    )
