import sqlite3
import time
import uuid
from pathlib import Path

from web.paths import app_data_dir

DEFAULT_DB_PATH = app_data_dir() / "auto_unlock_history.db"

# Metadata only -- which wallet, which vault label matched (if any), when.
# NO column for the raw matched password/value exists here at all -- a
# schema-level guarantee, not just an application-level promise not to
# write it. The once-only in-memory job result (web/jobs.py) is still the
# only place the real value is ever shown; this table just makes "did
# wallet X ever unlock, and with which saved password" answerable again
# after a restart, once the original job is long gone from memory.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS auto_unlock_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    wallet_path TEXT NOT NULL,
    vault_label TEXT,
    matched INTEGER NOT NULL,
    run_at REAL NOT NULL
);
"""

_MIGRATIONS = []


def _connect(db_path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    for statement in _MIGRATIONS:
        try:
            conn.execute(statement)
        except sqlite3.OperationalError:
            pass  # already migrated
    return conn


def record_auto_unlock_run(wallet_results, db_path=DEFAULT_DB_PATH):
    """
    Records one completed auto-unlock job -- one row per wallet tried,
    grouped under a shared run_id.

    :param wallet_results: {wallet_path: {"vault_label": str|None, "value": str|None}}
        -- the exact shape _run_auto_unlock_job already builds (auo-01).
        Only vault_label is persisted; "value" is deliberately never
        touched by this function.
    :return: the generated run_id.
    """
    run_id = str(uuid.uuid4())
    run_at = time.time()
    conn = _connect(db_path)
    try:
        conn.executemany(
            "INSERT INTO auto_unlock_runs (run_id, wallet_path, vault_label, matched, run_at) VALUES (?, ?, ?, ?, ?)",
            [
                (run_id, wallet_path, result.get("vault_label"), 1 if result.get("vault_label") else 0, run_at)
                for wallet_path, result in wallet_results.items()
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return run_id


def list_auto_unlock_history(db_path=DEFAULT_DB_PATH):
    """
    :return: [{"run_id", "run_at", "wallets": [{"wallet_path", "vault_label", "matched"}, ...]}, ...],
        newest run first, wallets within a run in original insertion order.
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT * FROM auto_unlock_runs ORDER BY run_at DESC, id ASC").fetchall()
    finally:
        conn.close()

    runs = {}
    order = []
    for row in rows:
        run_id = row["run_id"]
        if run_id not in runs:
            runs[run_id] = {"run_id": run_id, "run_at": row["run_at"], "wallets": []}
            order.append(run_id)
        runs[run_id]["wallets"].append(
            {"wallet_path": row["wallet_path"], "vault_label": row["vault_label"], "matched": bool(row["matched"])}
        )
    return [runs[run_id] for run_id in order]


def latest_status_by_wallet_path(db_path=DEFAULT_DB_PATH):
    """
    The cheap, always-live half of Findings' credential-status join
    (ccu-02): for each wallet_path that has ever appeared in an
    auto-unlock run, only the single most recent row -- "has this wallet
    been tried, and what happened last time" -- not the full history
    list_auto_unlock_history() already provides.

    :return: {wallet_path: {"matched": bool, "vault_label": str|None,
        "run_at": float}}. A wallet_path with no row at all is simply
        absent from the dict -- callers treat that as "not yet tried."
    """
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT * FROM auto_unlock_runs ORDER BY run_at DESC, id DESC").fetchall()
    finally:
        conn.close()

    latest = {}
    for row in rows:
        wallet_path = row["wallet_path"]
        if wallet_path not in latest:
            latest[wallet_path] = {
                "matched": bool(row["matched"]),
                "vault_label": row["vault_label"],
                "run_at": row["run_at"],
            }
    return latest


def clear_auto_unlock_history(db_path=DEFAULT_DB_PATH):
    """Deletes every recorded row -- has no effect on the vault or any wallet file."""
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM auto_unlock_runs")
        conn.commit()
    finally:
        conn.close()
