import threading
import time
import uuid

_jobs = {}
_lock = threading.Lock()


def run_job(fn, *args, **kwargs):
    """
    Start fn(*args, **kwargs) in a background daemon thread, tracked in an
    in-memory registry. Single local user, one-scan-at-a-time is the
    realistic usage pattern; nothing here prevents running several jobs
    concurrently against different inputs.

    :return: job_id (str) usable with get_job().
    """
    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = {
            "status": "running",
            "result": None,
            "error": None,
            "started_at": time.time(),
        }

    def _target():
        try:
            result = fn(*args, **kwargs)
            with _lock:
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["result"] = result
        except Exception as e:
            with _lock:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = str(e)

    threading.Thread(target=_target, daemon=True).start()
    return job_id


def get_job(job_id):
    """:return: a copy of the job's current state dict, or None if unknown."""
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job is not None else None
