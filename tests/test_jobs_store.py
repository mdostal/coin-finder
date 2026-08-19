import sqlite3
import time

from web import jobs_store


def test_job_survives_a_fresh_connection_against_the_same_db_file(tmp_path):
    """
    sse-04's core durability claim: web/jobs.py's old in-memory dict was
    wiped on every app restart -- confirmed as the exact reason a real
    dead backend lost an entire multi-hour scan job outright, not just
    its progress. jobs_store never holds a module-level connection across
    calls (see _connect()'s docstring) -- every call opens fresh and
    closes -- so this proves the job's existence and state live in the
    db FILE itself, not in anything a real restart would wipe: reading it
    back with a totally independent, hand-rolled sqlite3 connection (not
    jobs_store.get_job() again, which would only prove jobs_store's own
    open/close pattern) must see everything a prior call committed.
    """
    db_path = tmp_path / "jobs.db"
    job_id = jobs_store.create_job(
        kind="find", label="/data/drive1", checkpoint_path="/out/checks/scan_checkpoint.db", db_path=db_path
    )
    jobs_store.update_progress(job_id, 5, None, "walking", db_path=db_path)

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT kind, label, status, checkpoint_path FROM jobs WHERE job_id = ?", (job_id,)
    ).fetchone()
    conn.close()

    assert row == ("find", "/data/drive1", "running", "/out/checks/scan_checkpoint.db")

    job = jobs_store.get_job(job_id, db_path=db_path)
    assert job["status"] == "running"
    assert job["progress"] == {"current": 5, "total": None, "message": "walking"}


def test_get_job_unknown_returns_none(tmp_path):
    db_path = tmp_path / "jobs.db"
    assert jobs_store.get_job("does-not-exist", db_path=db_path) is None


def test_create_job_checkpoint_path_defaults_to_none(tmp_path):
    db_path = tmp_path / "jobs.db"
    job_id = jobs_store.create_job(kind="crawl", db_path=db_path)

    job = jobs_store.get_job(job_id, db_path=db_path)

    assert job["checkpoint_path"] is None


def test_update_status_done_stores_json_result(tmp_path):
    db_path = tmp_path / "jobs.db"
    job_id = jobs_store.create_job(db_path=db_path)

    jobs_store.update_status(job_id, "done", result={"output_dir": "/out/x"}, db_path=db_path)

    job = jobs_store.get_job(job_id, db_path=db_path)
    assert job["status"] == "done"
    assert job["result"] == {"output_dir": "/out/x"}
    assert job["error"] is None


def test_update_status_error_stores_error_and_no_result(tmp_path):
    db_path = tmp_path / "jobs.db"
    job_id = jobs_store.create_job(db_path=db_path)

    jobs_store.update_status(job_id, "error", error="boom", db_path=db_path)

    job = jobs_store.get_job(job_id, db_path=db_path)
    assert job["status"] == "error"
    assert job["error"] == "boom"
    assert job["result"] is None


def test_update_status_to_paused(tmp_path):
    """The new sse-04 status -- alongside running/done/error -- reachable
    without a result or error, since a pause is a clean stop, not a
    completion or a failure."""
    db_path = tmp_path / "jobs.db"
    job_id = jobs_store.create_job(kind="check-balances", db_path=db_path)

    jobs_store.update_status(job_id, "paused", db_path=db_path)

    job = jobs_store.get_job(job_id, db_path=db_path)
    assert job["status"] == "paused"
    assert job["result"] is None
    assert job["error"] is None


def test_update_progress_is_a_noop_for_unknown_job_id(tmp_path):
    """A background thread calling this for a job it no longer knows the
    fate of (e.g. long since consumed) has no good way to handle an
    error -- must not raise."""
    db_path = tmp_path / "jobs.db"
    jobs_store.update_progress("does-not-exist", 1, 2, "x", db_path=db_path)  # must not raise


def test_list_jobs_newest_first(tmp_path):
    db_path = tmp_path / "jobs.db"
    first = jobs_store.create_job(kind="a", db_path=db_path)
    time.sleep(0.01)
    second = jobs_store.create_job(kind="b", db_path=db_path)

    ids = [j["job_id"] for j in jobs_store.list_jobs(db_path=db_path)]

    assert ids.index(second) < ids.index(first)


def test_running_jobs_count_counts_only_running(tmp_path):
    db_path = tmp_path / "jobs.db"
    a = jobs_store.create_job(db_path=db_path)
    jobs_store.create_job(db_path=db_path)
    jobs_store.update_status(a, "done", db_path=db_path)

    assert jobs_store.running_jobs_count(db_path=db_path) == 1


def test_delete_job_removes_the_row(tmp_path):
    db_path = tmp_path / "jobs.db"
    job_id = jobs_store.create_job(secret=True, db_path=db_path)

    jobs_store.delete_job(job_id, db_path=db_path)

    assert jobs_store.get_job(job_id, db_path=db_path) is None


def test_connect_creates_parent_directory(tmp_path):
    db_path = tmp_path / "nested" / "dir" / "jobs.db"

    jobs_store.create_job(db_path=db_path)

    assert db_path.exists()
