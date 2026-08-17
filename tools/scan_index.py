import hashlib
import json
import sqlite3
import time
from pathlib import Path

from web.paths import app_data_dir

# web/paths.py has zero Flask dependency (web/__init__.py is empty, and
# app_data_dir() itself only imports sys/pathlib) -- safe to reuse here
# without pulling tools/ into a Flask-app coupling it has never had.
DEFAULT_DB_PATH = app_data_dir() / "scan_index.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scanned_files (
    file_hash TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    first_seen_at REAL NOT NULL,
    results_json TEXT NOT NULL
)
"""


def _connect(db_path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def hash_file_bytes(content):
    """sha256 hex digest of already-in-memory file bytes -- content-based,
    not path-based, so the same file at a different path (a backup copy on
    another drive) is still recognized."""
    return hashlib.sha256(content).hexdigest()


def is_known(file_hash, db_path=DEFAULT_DB_PATH):
    """:return: the previously recorded {coin: [addresses]} result for this exact file content, or None if never seen."""
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT results_json FROM scanned_files WHERE file_hash = ?", (file_hash,)).fetchone()
        if row is None:
            return None
        return json.loads(row["results_json"])
    finally:
        conn.close()


def record_scanned_file(file_hash, file_path, results, db_path=DEFAULT_DB_PATH):
    """
    Records that this exact file content has been analyzed, with its
    result, so a future scan of the same content (at any path) can skip
    re-analyzing it. First-seen path/time wins on a re-record of the same
    hash (INSERT OR IGNORE) -- which path/time gets stored doesn't matter
    for the dedup use case, only the hash and result do.
    """
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO scanned_files (file_hash, file_path, first_seen_at, results_json) VALUES (?, ?, ?, ?)",
            (file_hash, file_path, time.time(), json.dumps(results)),
        )
        conn.commit()
    finally:
        conn.close()


def list_scanned_files(db_path=DEFAULT_DB_PATH):
    """:return: [{"file_hash", "file_path", "first_seen_at"}, ...], newest first."""
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT file_hash, file_path, first_seen_at FROM scanned_files ORDER BY first_seen_at DESC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def clear_scan_index(db_path=DEFAULT_DB_PATH):
    """Hard-deletes the entire dedup index -- mirrors web.findings.clear_all_findings()."""
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM scanned_files")
        conn.commit()
    finally:
        conn.close()
