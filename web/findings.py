import sqlite3
import time
from pathlib import Path

from web.paths import app_data_dir

DEFAULT_DB_PATH = app_data_dir() / "findings.db"

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
    watched INTEGER NOT NULL DEFAULT 0,
    watch_note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (coin, address)
)
"""

# Columns added after the table's original release -- `CREATE TABLE IF NOT
# EXISTS` above only applies to a brand new db file; an existing
# findings.db on disk from before these columns existed needs each one
# added explicitly. Each entry is (column, definition); `ALTER TABLE ADD
# COLUMN` on a column that already exists raises OperationalError, which
# this treats as "already migrated" and ignores -- safe to run on every
# connect, not just once.
_MIGRATIONS = [
    ("watched", "INTEGER NOT NULL DEFAULT 0"),
    ("watch_note", "TEXT NOT NULL DEFAULT ''"),
]


def _connect(db_path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    for column, definition in _MIGRATIONS:
        try:
            conn.execute(f"ALTER TABLE findings ADD COLUMN {column} {definition}")
        except sqlite3.OperationalError:
            pass  # already migrated
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
    """
    :return: [{"coin", "address", "balance", "source_path", "source_label",
        "status", "first_seen_at", "last_checked_at", "watched",
        "watch_note"}, ...], watched findings first, newest-checked within
        each group -- a watched hypothesis (e.g. "suspected mining-wallet
        chain") should never scroll off the bottom of a long list.
    """
    conn = _connect(db_path)
    try:
        query = "SELECT * FROM findings"
        if not include_archived:
            query += " WHERE status != 'archived'"
        query += " ORDER BY watched DESC, last_checked_at DESC"
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


def set_watched(coin, address, watched, note="", db_path=DEFAULT_DB_PATH):
    """
    Marks/unmarks a finding as watched, with an optional free-text
    hypothesis note (e.g. "suspected mining-wallet chain -- ~5 coins in,
    transferred out in equal chunks, expect a matching holding wallet").
    Watched findings sort to the top of list_findings() regardless of
    status, so a candidate worth tracking down doesn't get buried as new
    scans add more rows.
    """
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE findings SET watched = ?, watch_note = ? WHERE coin = ? AND address = ?",
            (1 if watched else 0, note, coin, address),
        )
        conn.commit()
    finally:
        conn.close()


def clear_all_findings(db_path=DEFAULT_DB_PATH):
    """
    Hard-deletes every finding -- unlike archive(), this is not
    reversible. For starting over cleanly, not for routine triage (that's
    what archive/unarchive are for).
    """
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM findings")
        conn.commit()
    finally:
        conn.close()
