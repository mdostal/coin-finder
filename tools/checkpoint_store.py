import sqlite3
import threading
from pathlib import Path

# 5s: real, not zero -- this repo had zero explicit WAL/busy-timeout on any
# sqlite3.connect() anywhere until now, which is fine for a single writer
# at a time but a real risk the moment more than one process/thread (e.g.
# a pause route opening its own connection against a running job's
# checkpoint file) writes to the same db concurrently.
DEFAULT_BUSY_TIMEOUT_MS = 5000

# Meta keys reserved for the store's own bookkeeping -- never treated as
# part of run_key, so a pause flag survives independently of whatever
# run-identity fields a given stage uses (start_path, input_file, ...).
_RESERVED_META_KEYS = {"paused"}


class CheckpointStore:
    """
    Generic, reusable sqlite-backed checkpoint store for any long-running,
    resumable pipeline stage -- extracted from tools/search_wallets.py's
    already-shipped design (v0.53.6), which fixed a real production OOM:
    the original checkpoint held every completed directory as a full path
    string in an in-memory Python set, and rewrote the *entire* sorted set
    to JSON on every flush (confirmed live: 34,199 directories in, already
    a 3.85MB file rewritten every ~20s, unbounded for the life of the
    scan). This store keeps both memory use and per-flush write cost flat
    regardless of how many units have been completed so far: membership
    checks and counts are real indexed SQL queries, never a full table
    load into Python, and flush() only ever writes the units buffered
    since the last flush, never the whole history.

    unit_id is deliberately opaque to the store -- a directory path
    (search), a file path (analyze), or a composite
    f"{coin}|{file_path}|{address}" (check_balances). The store never
    needs to know what a unit *means*, only whether it's done -- this is
    what lets one module serve every stage instead of each stage
    reinventing its own checkpoint format (search: sqlite, check_balances/
    crawl: full-dict-rewrite JSON -- three formats for the same problem).

    run_key identifies "which run is this" (e.g. {"start_path": ...} for
    search, {"input_file": ...} for analyze/check_balances). Opening the
    store against an existing file recorded under a DIFFERENT run_key is
    treated as a stale leftover from an unrelated run (there is exactly
    one run per checkpoint_path in practice) -- its completed units are
    wiped and the file is reused fresh, rather than left on disk unread or
    incorrectly treated as this run's own progress.

    units_table/unit_column default to a generic ("completed_units",
    "unit_id") schema, but are overridable so a caller can reproduce an
    exact pre-existing schema byte-for-byte -- search_wallets.py passes
    units_table="completed_dirs", unit_column="path" specifically so
    web/app.py's raw-sqlite interrupted-scan reads (and any leftover
    checkpoint file from before this extraction) keep working unmodified.

    Thread-safe by design, not just by accident: every public method that
    touches self.conn or the in-memory pending buffer is serialized
    through a single internal RLock (reentrant so delete()'s own call
    into close() doesn't self-deadlock). This matters for real, not
    hypothetically -- sqlite3 connections default to check_same_thread=
    True, so a second thread calling any conn method at all raises
    ProgrammingError immediately; the sse-03 search-walk thread pool
    calls is_completed/mark_completed/flush directly from worker
    threads, and check_wallet_balances' existing ThreadPoolExecutor
    (sse-02) already does the same for mark_completed/flush from inside
    check_one() once CHECKPOINT_EVERY_ADDRESSES/SECONDS trips -- both
    would hit that exact ProgrammingError on a real multi-address run
    without check_same_thread=False + this lock. One process's worker
    threads sharing one connection under a lock is the supported sqlite3
    pattern; true multi-*process* writers (e.g. analyze's
    multiprocessing.Pool) are a different problem this does NOT solve,
    which is exactly why analyze keeps all its store writes in the main
    process instead (see structured-outline.md R4).
    """

    def __init__(
        self,
        checkpoint_path,
        run_key,
        units_table="completed_units",
        unit_column="unit_id",
        busy_timeout_ms=DEFAULT_BUSY_TIMEOUT_MS,
    ):
        self.checkpoint_path = str(checkpoint_path)
        self.run_key = {str(k): str(v) for k, v in run_key.items()}
        self.units_table = units_table
        self.unit_column = unit_column

        # Buffered, in-memory units marked completed since the last
        # flush() -- bounded by flush cadence (a caller's own
        # CHECKPOINT_EVERY_* thresholds), never by total completed count.
        # This -- not a growing set of every unit ever completed -- is
        # exactly what keeps memory flat versus the original bug.
        self._pending = []
        self._pending_set = set()

        # Reentrant -- delete() calls close() while already holding this
        # lock itself; a plain Lock would deadlock on that nested call.
        self._lock = threading.RLock()

        Path(self.checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: this store is handed to real worker
        # threads (see class docstring) -- every access is still funneled
        # through self._lock below, which is what actually makes sharing
        # one connection across threads safe, not this flag alone.
        self.conn = sqlite3.connect(self.checkpoint_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
        self.conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self.conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self.units_table} ({self.unit_column} TEXT PRIMARY KEY)"
        )
        self.conn.commit()
        self._sync_run_key()

    def _sync_run_key(self):
        rows = self.conn.execute("SELECT key, value FROM meta").fetchall()
        stored = {key: value for key, value in rows if key not in _RESERVED_META_KEYS}

        if not stored:
            for key, value in self.run_key.items():
                self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
            self.conn.commit()
            return

        if stored == self.run_key:
            return

        # Different run -- same precedent as tonight's already-shipped
        # search checkpoint: treat as a stale leftover, wipe, reuse fresh.
        self.conn.execute(f"DELETE FROM {self.units_table}")
        for key in stored:
            if key not in self.run_key:
                self.conn.execute("DELETE FROM meta WHERE key = ?", (key,))
        for key, value in self.run_key.items():
            self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
        self.conn.commit()

    def is_completed(self, unit_id):
        with self._lock:
            if unit_id in self._pending_set:
                return True
            row = self.conn.execute(
                f"SELECT 1 FROM {self.units_table} WHERE {self.unit_column} = ?", (unit_id,)
            ).fetchone()
            return row is not None

    def mark_completed(self, unit_id):
        """Buffers unit_id in memory -- see flush() for when it actually
        hits disk. Already-committed or already-pending units are quietly
        deduplicated rather than growing the buffer unnecessarily."""
        with self._lock:
            if unit_id in self._pending_set:
                return
            self._pending.append(unit_id)
            self._pending_set.add(unit_id)

    def flush(self):
        """Commits every unit buffered since the last flush in a single
        transaction, then clears the buffer. Cost is proportional to what
        was buffered since the last flush ONLY -- never to how many units
        have been completed in total, which is exactly what keeps this
        flat regardless of scan size (see class docstring)."""
        with self._lock:
            if not self._pending:
                return
            self.conn.executemany(
                f"INSERT OR IGNORE INTO {self.units_table} ({self.unit_column}) VALUES (?)",
                [(unit_id,) for unit_id in self._pending],
            )
            self.conn.commit()
            self._pending.clear()
            self._pending_set.clear()

    def count_completed(self):
        """SQL COUNT(*) -- never loads all unit ids into Python, so this
        stays cheap and flat no matter how many units are completed."""
        with self._lock:
            row = self.conn.execute(f"SELECT COUNT(*) FROM {self.units_table}").fetchone()
            return row[0]

    def is_paused(self):
        with self._lock:
            row = self.conn.execute("SELECT value FROM meta WHERE key = 'paused'").fetchone()
            return row is not None and row[0] == "1"

    def request_pause(self):
        """Sets the pause flag, durably and immediately visible to any
        other connection open against this same checkpoint_path (e.g. a
        running job's own store, checked between checkpoint flushes) --
        the mechanism a future pause route uses without needing to know
        which stage/process it's pausing."""
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('paused', '1')")
            self.conn.commit()

    def clear_pause(self):
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('paused', '0')")
            self.conn.commit()

    def close(self):
        with self._lock:
            self.conn.close()

    def delete(self):
        """Removes the checkpoint file (and any WAL/SHM sidecar files) on
        clean completion -- there's nothing left to resume once a run
        finishes, same as the original search-checkpoint behavior."""
        self.close()
        Path(self.checkpoint_path).unlink(missing_ok=True)
        Path(f"{self.checkpoint_path}-wal").unlink(missing_ok=True)
        Path(f"{self.checkpoint_path}-shm").unlink(missing_ok=True)


class CheckpointPaused(Exception):
    """
    Raised by a pipeline stage function (search_for_wallets, analyze_wallets,
    check_wallet_balances) when it notices mid-run that its CheckpointStore's
    is_paused() has become true and stops early. Always raised only AFTER
    whatever unit(s) were already in flight have fully finished and any
    buffered checkpoint progress has been flushed -- confirmed pause
    semantics (sse-04): let in-flight work finish, never abort mid-write.

    web/jobs.py's start_job() catches this specifically (not just any
    Exception) to report the job's status as "paused" rather than "error".
    """


def request_pause_for(checkpoint_path):
    """
    Sets the pause flag on an existing checkpoint file at checkpoint_path
    directly, WITHOUT opening a full CheckpointStore -- and therefore
    without ever needing to know (or risk mismatching) that store's
    run_key. Opening a real CheckpointStore with the wrong run_key would
    make _sync_run_key() treat this as an unrelated stale run and wipe
    its completed_units table -- exactly the kind of real-progress-loss
    bug a pause action must never risk. This is the mechanism a pause
    route uses: it knows a job's checkpoint_path (recorded at job
    creation), never the run_key the actual running stage opened it
    with.

    Uses the same busy_timeout discipline as CheckpointStore itself,
    since this connection may race a running job's own flush() -- see
    DEFAULT_BUSY_TIMEOUT_MS's docstring above.

    :return: True if the flag was set, False if checkpoint_path does not
        exist yet -- nothing is running against it to pause (e.g. a
        multi-stage job whose next stage hasn't started its own
        checkpoint file yet; whichever stage IS currently running has a
        checkpoint file that does exist, and gets paused normally).
    """
    if not Path(checkpoint_path).exists():
        return False
    conn = sqlite3.connect(str(checkpoint_path))
    try:
        conn.execute(f"PRAGMA busy_timeout={DEFAULT_BUSY_TIMEOUT_MS}")
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('paused', '1')")
        conn.commit()
    finally:
        conn.close()
    return True


def clear_pause_for(checkpoint_path):
    """
    Inverse of request_pause_for() -- clears the pause flag so a resumed
    run doesn't immediately notice "paused" again and stop after zero new
    work. Same run_key-agnostic, no-full-CheckpointStore approach, same
    no-op-if-missing behavior.
    """
    if not Path(checkpoint_path).exists():
        return False
    conn = sqlite3.connect(str(checkpoint_path))
    try:
        conn.execute(f"PRAGMA busy_timeout={DEFAULT_BUSY_TIMEOUT_MS}")
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('paused', '0')")
        conn.commit()
    finally:
        conn.close()
    return True
