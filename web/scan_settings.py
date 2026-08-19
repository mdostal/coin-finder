import json
import os
import sqlite3
from pathlib import Path

from tools.check_wallet_balances import GLOBAL_MAX_WORKERS, PER_COIN_MAX_CONCURRENCY
from web.paths import app_data_dir

# Small key-value settings store, same pattern as web/auto_unlock_history.py
# and web/vault.py's own simplicity (see structured-outline.md #1.6) --
# not a new heavyweight config system.
DEFAULT_DB_PATH = app_data_dir() / "scan_settings.db"

VALID_MODES = ("auto", "custom")

# The full four-field profile from structured-outline.md #1.6 -- all four
# fields are now read by a job dispatch route (sse-06 generalized sse-02's
# check_balances-only wiring to search_walk_threads/analyze_processes too;
# see web.app's _run_find_job for those two, and
# _run_check_balances_job/_run_check_balances_selected_job for the
# original two).
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


def _detected_cpu_count():
    """
    os.cpu_count() can return None on a machine where the core count
    isn't determinable at all (rare, but stdlib docs call it out
    explicitly) -- fall back to 1, the most conservative possible value,
    rather than let a None flow into the arithmetic below.
    """
    return os.cpu_count() or 1


def auto_search_walk_threads(cpu_count=None):
    """
    structured-outline.md #1.6 formula table: `min(4, max(1, cpu_count()
    // 2))`. Directory listing is I/O-bound, and walk_threads is already
    known to interact with a real shared rclone API quota (see
    tools/search_wallets.py's DEFAULT_WALK_THREADS comment) -- more cores
    buys nothing past a small, deliberately conservative handful of
    concurrent walkers.

    :param cpu_count: override the live os.cpu_count() reading -- lets a
        caller (or a test) compute the formula for an arbitrary core
        count without needing to monkeypatch os.cpu_count() itself.
        None (the default) reads the current machine's count live.
    """
    cpu_count = _detected_cpu_count() if cpu_count is None else cpu_count
    return min(4, max(1, cpu_count // 2))


def auto_analyze_processes(cpu_count=None):
    """
    structured-outline.md #1.6 formula table: `max(1, cpu_count() - 1)`.
    Analyze is CPU-bound regex matching over file content -- use most
    cores, leave one free for the Flask app process itself.

    :param cpu_count: see auto_search_walk_threads's own docstring.
    """
    cpu_count = _detected_cpu_count() if cpu_count is None else cpu_count
    return max(1, cpu_count - 1)


def get_auto_profile():
    """
    Live-computed "what would auto mode use right now" for all four
    fields -- powers the settings page's read-only auto display. Always
    computed fresh from the current machine's os.cpu_count() at call
    time, never cached/stored -- an app-data directory ever copied to
    different hardware must reflect that new machine's core count on its
    very next read, not a number baked in on whatever machine originally
    wrote scan_settings.db (sse-06 acceptance criteria).

    check_balances' two fields are pinned to today's tuned constants
    here, unconditionally -- confirmed requirement: they're tuned against
    a real external API's rate limit (see check_wallet_balances.py's own
    PER_COIN_MAX_CONCURRENCY/GLOBAL_MAX_WORKERS comments), not local
    hardware, so cpu_count() must never drive them.
    """
    return {
        "search_walk_threads": auto_search_walk_threads(),
        "analyze_processes": auto_analyze_processes(),
        "check_balances_global_workers": GLOBAL_MAX_WORKERS,
        "check_balances_per_coin_concurrency": PER_COIN_MAX_CONCURRENCY,
    }


def _resolve(field, auto_fn, settings):
    """
    Shared resolution rule for a single field: a "custom" mode with a
    real (non-null) override for this field wins outright -- auto_fn is
    never called in that case, satisfying the confirmed requirement that
    auto-detection isn't consulted at all once a custom value is set.
    Anything else (mode == "auto", or "custom" with this one field left
    null) falls back to auto_fn() -- called lazily, only when actually
    needed.
    """
    if settings["mode"] == "custom":
        override = settings["overrides"].get(field)
        if override is not None:
            return override
    return auto_fn()


def resolve_search_walk_threads(db_path=DEFAULT_DB_PATH):
    """
    The value the next search job dispatch should use for
    tools.search_wallets.search_for_wallets()'s walk_threads parameter.
    See _resolve()/auto_search_walk_threads() for the auto/custom rule.
    """
    settings = get_settings(db_path)
    return _resolve("search_walk_threads", auto_search_walk_threads, settings)


def resolve_analyze_processes(db_path=DEFAULT_DB_PATH):
    """
    The value the next analyze job dispatch should use for
    tools.analyze_wallets.analyze_wallets()'s processes parameter. See
    _resolve()/auto_analyze_processes() for the auto/custom rule.
    """
    settings = get_settings(db_path)
    return _resolve("analyze_processes", auto_analyze_processes, settings)
