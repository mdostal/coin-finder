import sqlite3
import time
from pathlib import Path

from web.paths import app_data_dir

DEFAULT_DB_PATH = app_data_dir() / "scan_history.db"

# An index only -- never the scan data itself. The actual results live in
# output_dir/find_summary.json (and, once a balance check runs,
# output_dir/checks/wallet_balances.json), both durable on their own.
# This table just makes past scans discoverable again after a restart.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    output_dir TEXT PRIMARY KEY,
    input_dir TEXT NOT NULL,
    files_found INTEGER NOT NULL,
    created_at REAL NOT NULL
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


def record_scan(input_dir, output_dir, files_found, db_path=DEFAULT_DB_PATH):
    """
    Records one completed Find (Stage 1) job so it can be found again after
    an app restart, independent of web/jobs.py's in-memory registry.
    output_dir is the primary key -- re-scanning the same directory (same
    DEFAULT_OUTPUT_ROOT / Path(input_dir).name) updates the existing row
    rather than accumulating duplicates.
    """
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO scans (output_dir, input_dir, files_found, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(output_dir) DO UPDATE SET
                input_dir = excluded.input_dir,
                files_found = excluded.files_found,
                created_at = excluded.created_at
            """,
            (output_dir, input_dir, files_found, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def list_scan_history(db_path=DEFAULT_DB_PATH):
    """:return: [{"output_dir", "input_dir", "files_found", "created_at"}, ...], newest first."""
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT * FROM scans ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def clear_scan_history(db_path=DEFAULT_DB_PATH):
    """Deletes every recorded index row -- never touches output_dir/find_summary.json on disk."""
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM scans")
        conn.commit()
    finally:
        conn.close()
