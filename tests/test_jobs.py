import inspect
import time

from tools.checkpoint_store import CheckpointPaused
from web import jobs


def _drain(job_id, timeout=2):
    started = time.time()
    while time.time() - started < timeout:
        job = jobs.get_job(job_id)
        if job["status"] != "running":
            return job
        time.sleep(0.01)
    raise TimeoutError(f"job {job_id} never finished")


def test_list_jobs_includes_kind_and_label():
    job_id = jobs.run_job(lambda: "ok", kind="scan", label="/Volumes/OldDrive")
    _drain(job_id)

    found = next(j for j in jobs.list_jobs() if j["job_id"] == job_id)
    assert found["kind"] == "scan"
    assert found["label"] == "/Volumes/OldDrive"


def test_list_jobs_defaults_kind_when_not_given():
    job_id = jobs.run_job(lambda: "ok")
    _drain(job_id)

    found = next(j for j in jobs.list_jobs() if j["job_id"] == job_id)
    assert found["kind"] == "job"
    assert found["label"] is None


def test_list_jobs_strips_secret_results_in_terminal_state():
    job_id = jobs.run_job(lambda: "hunter2", secret=True, kind="unlock", label="wallet.dat")
    _drain(job_id)

    found = next(j for j in jobs.list_jobs() if j["job_id"] == job_id)
    assert found["result"] is None
    assert found["status"] == "done"


def test_list_jobs_sorted_newest_first():
    first = jobs.run_job(lambda: "a")
    _drain(first)
    time.sleep(0.01)
    second = jobs.run_job(lambda: "b")
    _drain(second)

    all_ids = [j["job_id"] for j in jobs.list_jobs()]
    assert all_ids.index(second) < all_ids.index(first)


def test_running_jobs_count_counts_only_running():
    done_job = jobs.run_job(lambda: "a")
    _drain(done_job)

    def _slow():
        time.sleep(1)
        return "b"

    running_job = jobs.run_job(_slow)
    try:
        assert jobs.running_jobs_count() >= 1
        found = next(j for j in jobs.list_jobs() if j["job_id"] == running_job)
        assert found["status"] == "running"
    finally:
        _drain(running_job, timeout=3)


# sse-04: web/jobs.py's registry moved from a plain in-memory dict to a
# sqlite-backed store (web/jobs_store.py) -- these confirm every existing
# web/app.py call site's contract is preserved exactly (acceptance
# criterion: "no call site needs to change"). New parameters are only
# ever appended, always with a default, so a caller that never passes
# them behaves byte-identical to before.


def test_create_job_signature_preserves_original_params_and_order():
    params = list(inspect.signature(jobs.create_job).parameters.values())
    assert [p.name for p in params[:3]] == ["secret", "kind", "label"]
    assert params[0].default is False
    assert params[1].default == "job"
    assert params[2].default is None


def test_start_job_signature_unchanged():
    params = list(inspect.signature(jobs.start_job).parameters)
    assert params[0] == "job_id"
    assert params[1] == "fn"


def test_report_progress_signature_unchanged():
    params = list(inspect.signature(jobs.report_progress).parameters)
    assert params == ["job_id", "current", "total", "message"]


def test_get_job_signature_unchanged():
    assert list(inspect.signature(jobs.get_job).parameters) == ["job_id"]


def test_create_job_records_checkpoint_path():
    job_id = jobs.create_job(kind="find", label="/data", checkpoint_path="/out/checks/scan_checkpoint.db")

    job = jobs.get_job(job_id)

    assert job["checkpoint_path"] == "/out/checks/scan_checkpoint.db"


def test_create_job_checkpoint_path_defaults_to_none_for_existing_callers():
    job_id = jobs.create_job(kind="crawl", label="3 address(es)")

    job = jobs.get_job(job_id)

    assert job["checkpoint_path"] is None


def test_run_job_forwards_checkpoint_path():
    job_id = jobs.run_job(lambda: "ok", kind="check-balances", checkpoint_path="/out/checks/balance_checkpoint.db")
    _drain(job_id)

    job = jobs.get_job(job_id)
    assert job["checkpoint_path"] == "/out/checks/balance_checkpoint.db"


def test_start_job_reports_paused_status_when_fn_raises_checkpoint_paused():
    """The mechanism a checkpoint-backed stage uses to signal a clean,
    user-requested pause (not a crash/error) -- start_job's own thread
    wrapper is what translates that into the job's status."""

    def _pausing():
        raise CheckpointPaused("search paused after 3 directories")

    job_id = jobs.create_job(kind="find")
    jobs.start_job(job_id, _pausing)

    job = _drain(job_id)

    assert job["status"] == "paused"
    assert job["error"] is None
    assert job["result"] is None


def test_paused_job_is_distinguishable_from_a_real_error():
    def _erroring():
        raise ValueError("actually broken")

    job_id = jobs.create_job(kind="find")
    jobs.start_job(job_id, _erroring)

    job = _drain(job_id)

    assert job["status"] == "error"
    assert job["error"] == "actually broken"
