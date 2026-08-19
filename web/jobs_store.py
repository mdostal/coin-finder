import json
import pickle
import sqlite3
import time
import uuid
from pathlib import Path

from web.paths import app_data_dir

# Same per-user app-data location every other persisted-state module in
# web/ already uses (web/scan_history.py, web/vault.py, ...) -- see
# web/paths.py's app_data_dir() docstring for why a frozen desktop build
# can't just use this file's own directory. gitignored, same as every
# other *.db this repo already has (see .gitignore's /web/jobs.db entry).
DEFAULT_DB_PATH = app_data_dir() / "jobs.db"

# sse-04: web/jobs.py's job registry used to be a plain in-memory dict
# (_jobs = {}), wiped on every app restart -- confirmed as the exact
# reason a real dead backend lost an entire multi-hour scan job outright
# (not just its progress: the job's very existence disappeared). This
# table is the durable replacement. checkpoint_path is what lets a
# pause route (web/app.py's POST /jobs/<job_id>/pause) find the right
# CheckpointStore file for a running job without needing to know which
# stage it wraps.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    label TEXT,
    status TEXT NOT NULL,
    started_at REAL NOT NULL,
    progress_json TEXT,
    result_blob BLOB,
    error TEXT,
    secret INTEGER NOT NULL DEFAULT 0,
    checkpoint_path TEXT
);
"""


def _connect(db_path):
    """
    Opens a fresh connection every call, same pattern as web/scan_history.py
    -- no long-lived module-level connection held across calls. This is
    also exactly what makes durability-across-a-restart real and testable:
    every read/write here already goes through open-write/read-close, so
    "the app restarted" is indistinguishable from "the next call opened a
    fresh connection" -- there is no in-Python cache to lose.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _row_to_dict(row):
    d = dict(row)
    result_blob = d.pop("result_blob")
    progress_json = d.pop("progress_json")
    d["result"] = pickle.loads(result_blob) if result_blob is not None else None
    d["progress"] = json.loads(progress_json) if progress_json is not None else None
    d["secret"] = bool(d["secret"])
    return d


def create_job(secret=False, kind="job", label=None, checkpoint_path=None, db_path=DEFAULT_DB_PATH):
    """
    Registers a new job row in "running" state and returns its job_id.
    checkpoint_path is optional -- only jobs wrapping a checkpoint-backed
    stage (search/analyze/check-balances) have one; None for every other
    job kind, same as before this column existed.
    """
    job_id = str(uuid.uuid4())
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO jobs (job_id, kind, label, status, started_at, secret, checkpoint_path)
            VALUES (?, ?, ?, 'running', ?, ?, ?)
            """,
            (job_id, kind, label, time.time(), int(secret), checkpoint_path),
        )
        conn.commit()
    finally:
        conn.close()
    return job_id


def update_status(job_id, status, result=None, error=None, db_path=DEFAULT_DB_PATH):
    """
    Terminal (or paused) status transition -- status is one of "done",
    "error", or "paused". A no-op (affects zero rows) for an unknown
    job_id, same silent-no-op contract report_progress()/update_progress()
    already has.

    result is pickled, not JSON-encoded -- the old in-memory dict this
    module replaces never constrained a job's result to JSON-safe shapes
    at all (it just held whatever Python object fn() returned), and at
    least one real job kind's result genuinely isn't JSON-representable:
    _run_bulk_extract_key_job returns {"results": {(wallet_path, address):
    {...}}} -- a dict keyed by tuples, which json.dumps() cannot encode.
    Pickling preserves that exactly, matching the signature/behavior
    parity this story requires. Only ever unpickles data this same
    process wrote (job results, never external/untrusted input), so the
    usual "don't unpickle untrusted data" caveat doesn't apply here.
    """
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE jobs SET status = ?, result_blob = ?, error = ? WHERE job_id = ?",
            (status, pickle.dumps(result) if result is not None else None, error, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_progress(job_id, current, total, message, db_path=DEFAULT_DB_PATH):
    """Silently a no-op for an unknown job_id -- a background thread
    calling this has no good way to handle that error (same contract as
    today's in-memory report_progress())."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE jobs SET progress_json = ? WHERE job_id = ?",
            (json.dumps({"current": current, "total": total, "message": message}), job_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_job(job_id, db_path=DEFAULT_DB_PATH):
    """:return: a dict of the job's current row, or None if unknown."""
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    return _row_to_dict(row) if row else None


def list_jobs(db_path=DEFAULT_DB_PATH):
    """Every job row, newest-first."""
    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT * FROM jobs ORDER BY started_at DESC").fetchall()
    finally:
        conn.close()
    return [_row_to_dict(row) for row in rows]


def running_jobs_count(db_path=DEFAULT_DB_PATH):
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'running'").fetchone()
    finally:
        conn.close()
    return row[0]


def delete_job(job_id, db_path=DEFAULT_DB_PATH):
    """Used only for a secret job's once-only result consumption (see
    web/jobs.py's consume_job_result()) -- bounds a found password/seed
    phrase's exposure window to a single read."""
    conn = _connect(db_path)
    try:
        conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
        conn.commit()
    finally:
        conn.close()
