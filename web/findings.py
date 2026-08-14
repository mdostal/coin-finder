import sqlite3
import time
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "findings.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS findings (
    coin TEXT NOT NULL,
    address TEXT NOT NULL,
    balance REAL,
    source_path TEXT,
    source_label TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    first_seen_at REAL NOT NULL,
    last_checked_at REAL NOT NULL,
    PRIMARY KEY (coin, address)
)
"""


def _connect(db_path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def record_finding(coin, address, balance, source_path=None, source_label=None, db_path=DEFAULT_DB_PATH):
    """
    Upserts one finding keyed on (coin, address). On an existing row,
    updates balance/last_checked_at (and source fields, if given) but
    leaves `status` untouched -- a routine re-scan must never silently
    un-archive a finding the user already reviewed and dismissed.
    first_seen_at is set only on true insert.
    """
    now = time.time()
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO findings (coin, address, balance, source_path, source_label, status, first_seen_at, last_checked_at)
            VALUES (?, ?, ?, ?, ?, 'new', ?, ?)
            ON CONFLICT(coin, address) DO UPDATE SET
                balance = excluded.balance,
                source_path = COALESCE(excluded.source_path, findings.source_path),
                source_label = COALESCE(excluded.source_label, findings.source_label),
                last_checked_at = excluded.last_checked_at
            """,
            (coin, address, balance, source_path, source_label, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def list_findings(include_archived=False, db_path=DEFAULT_DB_PATH):
    """:return: [{"coin", "address", "balance", "source_path", "source_label", "status", "first_seen_at", "last_checked_at"}, ...], newest-checked first."""
    conn = _connect(db_path)
    try:
        query = "SELECT * FROM findings"
        if not include_archived:
            query += " WHERE status != 'archived'"
        query += " ORDER BY last_checked_at DESC"
        rows = conn.execute(query).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def archive(coin, address, db_path=DEFAULT_DB_PATH):
    conn = _connect(db_path)
    try:
        conn.execute("UPDATE findings SET status = 'archived' WHERE coin = ? AND address = ?", (coin, address))
        conn.commit()
    finally:
        conn.close()


def unarchive(coin, address, db_path=DEFAULT_DB_PATH):
    conn = _connect(db_path)
    try:
        conn.execute("UPDATE findings SET status = 'new' WHERE coin = ? AND address = ?", (coin, address))
        conn.commit()
    finally:
        conn.close()


def archive_all_zero_balance(db_path=DEFAULT_DB_PATH):
    """Archives every finding with balance == 0.0 and status == 'new' -- never touches NULL (inconclusive) balances."""
    conn = _connect(db_path)
    try:
        conn.execute("UPDATE findings SET status = 'archived' WHERE balance = 0.0 AND status = 'new'")
        conn.commit()
    finally:
        conn.close()
