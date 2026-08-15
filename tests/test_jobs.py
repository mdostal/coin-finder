import time

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
