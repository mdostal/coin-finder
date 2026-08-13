import time

from web.jobs import get_job, report_progress, run_job


def _wait_for_terminal(job_id, timeout_iterations=100):
    job = None
    for _ in range(timeout_iterations):
        job = get_job(job_id)
        if job["status"] != "running":
            break
        time.sleep(0.02)
    return job


def test_job_starts_with_no_progress():
    job_id = run_job(lambda: "done")
    job = get_job(job_id)
    assert job["progress"] is None


def test_report_progress_updates_the_job():
    started = __import__("threading").Event()
    proceed = __import__("threading").Event()

    def slow_job():
        started.set()
        proceed.wait(timeout=5)
        return "ok"

    job_id = run_job(slow_job)
    started.wait(timeout=5)
    report_progress(job_id, 3, 10, "checking addresses")

    job = get_job(job_id)
    assert job["progress"] == {"current": 3, "total": 10, "message": "checking addresses"}

    proceed.set()
    _wait_for_terminal(job_id)


def test_report_progress_on_unknown_job_id_does_not_raise():
    report_progress("does-not-exist", 1, 1)


def test_job_without_progress_calls_stays_none_throughout():
    job_id = run_job(lambda: "done")
    job = _wait_for_terminal(job_id)
    assert job["status"] == "done"
    assert job["progress"] is None
