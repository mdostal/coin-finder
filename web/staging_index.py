import hashlib
import logging
import shutil
import sqlite3
import time
from pathlib import Path

from web.paths import app_data_dir

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = app_data_dir() / "staging_index.db"

# Standalone default for direct/test use of this module -- web/app.py
# always passes its own DEFAULT_STAGING_DIR (which additionally accounts
# for a frozen build's app-data relocation) explicitly at every real call
# site, so this default is never actually relied on there.
DEFAULT_STAGING_DIR = app_data_dir() / "staged"

# A staged copy's filename is f"{sha256-prefix}-{original_name}" -- see
# stage_and_index()'s docstring for why.
_HASH_PREFIX_LEN = 12
_HASH_CHUNK_SIZE = 1024 * 1024

# Soft heads-up threshold, not a hard cap -- see stage_and_index()'s
# docstring.
SIZE_WARNING_THRESHOLD_BYTES = 1024 ** 3  # 1GB

_SCHEMA = """
CREATE TABLE IF NOT EXISTS staging_index (
    staged_path TEXT PRIMARY KEY,
    original_source_path TEXT NOT NULL,
    coin TEXT NOT NULL,
    address TEXT NOT NULL,
    source_label TEXT,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    staged_at REAL NOT NULL,
    decision TEXT NOT NULL DEFAULT 'undecided'
)
"""

# Columns added after the table's original release -- see web/findings.py's
# own _MIGRATIONS for why this list (currently empty) exists at all: safe
# to run on every connect, not just once, and keeps this module ready for
# a future column without needing a one-off migration script.
_MIGRATIONS = []


def _connect(db_path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    for column, definition in _MIGRATIONS:
        try:
            conn.execute(f"ALTER TABLE staging_index ADD COLUMN {column} {definition}")
        except sqlite3.OperationalError:
            pass  # already migrated
    return conn


def _content_hash(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_HASH_CHUNK_SIZE), b""):
            hasher.update(chunk)
    return hasher.hexdigest()[:_HASH_PREFIX_LEN]


def _file_size(path):
    """Broken out for testability -- the 1GB-warning test mocks this rather than writing a real gigabyte-sized fixture file."""
    return Path(path).stat().st_size


def _total_staged_size(conn):
    return conn.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM staging_index").fetchone()[0]


def stage_and_index(source_path, coin, address, source_label, staging_dir=DEFAULT_STAGING_DIR, db_path=DEFAULT_DB_PATH):
    """
    Copies source_path into staging_dir under a content-hash-based name
    (f"{sha256-prefix}-{original_name}") and records an index entry
    mapping the staged copy back to the original source_path/coin/
    address/source_label -- so if the original file's drive/mount later
    disappears, the finding it backed still has a local copy of its
    source.

    Content-hash naming (rather than the existing /item/stage route's
    flat original-basename naming) fixes that route's same-basename
    collision gap as a side effect: two different real files that happen
    to share a filename now hash to two different staged names and both
    stage cleanly. It also gives re-staging the exact same file (e.g. a
    re-scan, or the same source file backing multiple findings) a free,
    correct dedup -- identical content always hashes to the identical
    staged path, so a staged_path already present in the index (checked
    first, before touching the filesystem) means this call is a no-op:
    no re-copy, no error, just the existing staged_path handed back.

    Keeps a running total of staged bytes (size_bytes summed across every
    indexed row) and logs one visible warning the first time that total
    crosses SIZE_WARNING_THRESHOLD_BYTES (1GB) -- a soft heads-up, not a
    hard cap: nothing here blocks the copy or raises. "first time"
    specifically: the warning only fires on the call whose own file is
    what tips the running total from under the threshold to at/over it,
    never on every subsequent call once already over.

    :return: the staged path (str), whether it was just copied or already existed.
    """
    source = Path(source_path)
    staging_dir = Path(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    digest = _content_hash(source)
    staged_path = staging_dir / f"{digest}-{source.name}"

    conn = _connect(db_path)
    try:
        existing = conn.execute(
            "SELECT staged_path FROM staging_index WHERE staged_path = ?", (str(staged_path),)
        ).fetchone()
        if existing is not None:
            return str(staged_path)

        if not staged_path.exists():
            shutil.copy2(source, staged_path)

        size_bytes = _file_size(staged_path)
        total_before = _total_staged_size(conn)
        total_after = total_before + size_bytes

        conn.execute(
            """
            INSERT INTO staging_index
                (staged_path, original_source_path, coin, address, source_label, size_bytes, staged_at, decision)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'undecided')
            """,
            (str(staged_path), str(source), coin, address, source_label, size_bytes, time.time()),
        )
        conn.commit()

        if total_before < SIZE_WARNING_THRESHOLD_BYTES <= total_after:
            logger.warning(
                "Staged files now total %.2f GB (crossed the 1GB soft threshold in %s) -- "
                "heads-up only, nothing is blocked.",
                total_after / (1024 ** 3),
                staging_dir,
            )

        return str(staged_path)
    finally:
        conn.close()


def list_staged_entries(db_path=DEFAULT_DB_PATH):
    """:return: [{"staged_path", "original_source_path", "coin", "address", "source_label", "size_bytes", "staged_at", "decision"}, ...], most recently staged first."""
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT * FROM staging_index ORDER BY staged_at DESC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_staged_entry(staged_path, db_path=DEFAULT_DB_PATH):
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM staging_index WHERE staged_path = ?", (str(staged_path),)).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def set_staged_decision(staged_path, decision, db_path=DEFAULT_DB_PATH):
    """
    Updates ONLY the `decision` column for staged_path -- 'keep' or
    'archived' (scpi-02's review page), same 'undecided' default as
    stage_and_index() leaves every new entry in. This never touches the
    staged copy on disk, and NEVER touches the real file at
    original_source_path in any way -- it is a pure sqlite UPDATE against
    this module's own index, nothing else. Deleting a user's real
    original file is out of scope for this entire epic; see
    web/app.py's staged_files_archive route for where that scope limit
    is enforced at the UI action level.

    A staged_path not present in the index is a silent no-op (0 rows
    updated) rather than an error -- mirrors get_staged_entry() returning
    None for the same case.
    """
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE staging_index SET decision = ? WHERE staged_path = ?", (decision, str(staged_path))
        )
        conn.commit()
    finally:
        conn.close()
