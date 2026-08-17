import threading
import time
import uuid

_jobs = {}
_lock = threading.Lock()


def create_job(secret=False, kind="job", label=None):
    """
    Registers a new job in "running" state and returns its id, without
    starting any work yet -- for callers that need the job_id before they
    can build the work closure (e.g. to wire a progress_callback bound to
    this exact job_id). Most callers want run_job() instead, which does
    both steps at once.

    :param kind: short machine-readable job type ("scan", "unlock",
        "drive-scan", ...) -- shown on /jobs so a job started from any page
        is still findable after navigating away. Defaults to "job" so
        existing call sites that don't pass it keep working unchanged.
    :param label: human-readable target of the job (a path, a filename)
        for the same /jobs listing. None is rendered as "-- " there.
    """
    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = {
            "status": "running",
            "result": None,
            "error": None,
            "started_at": time.time(),
            "secret": secret,
            "progress": None,
            "kind": kind,
            "label": label,
        }
    return job_id


def start_job(job_id, fn, *args, **kwargs):
    """Runs fn(*args, **kwargs) in a background daemon thread for an already-created job_id (see create_job())."""

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


def run_job(fn, *args, secret=False, kind="job", label=None, **kwargs):
    """
    Start fn(*args, **kwargs) in a background daemon thread, tracked in an
    in-memory registry. Single local user, one-scan-at-a-time is the
    realistic usage pattern; nothing here prevents running several jobs
    concurrently against different inputs.

    :param secret: True for jobs whose result may itself be sensitive (e.g.
        an unlock attempt's found password). Secret job results are hidden
        from get_job()/the polling API entirely -- only consume_job_result()
        can read one, exactly once, before it is deleted from the registry.
    :param kind: see create_job().
    :param label: see create_job().
    :return: job_id (str) usable with get_job().
    """
    job_id = create_job(secret=secret, kind=kind, label=label)
    start_job(job_id, fn, *args, **kwargs)
    return job_id


def report_progress(job_id, current, total, message=""):
    """
    Updates a running job's progress -- called mid-execution by a tool's
    progress_callback. Silently a no-op for an unknown job_id (a job that
    already finished, or was never started) rather than raising, since a
    background thread calling this has no good way to handle that error.
    """
    with _lock:
        if job_id in _jobs:
            _jobs[job_id]["progress"] = {"current": current, "total": total, "message": message}


def get_job(job_id):
    """
    :return: a copy of the job's current state dict, or None if unknown.
        For a secret job in a terminal state (done/error), "result" is
        stripped from the copy -- this is the path polled repeatedly by the
        frontend, so a secret-bearing result must never be readable here,
        only via consume_job_result().
    """
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        copy = dict(job)

    if copy.get("secret") and copy["status"] in ("done", "error"):
        copy["result"] = None
    return copy


def list_jobs():
    """
    Every job currently known, newest-first -- the data behind /jobs.
    Exists so a job started from any page is still checkable after
    navigating away, which was the whole point of adding this: a
    long-running scan looking "cancelled" once you leave its own status
    page. Secret job results are stripped in terminal states, exactly like
    get_job() -- this is a listing view, never the once-only reveal path.

    :return: [{"job_id", "kind", "label", "status", ...}, ...]
    """
    with _lock:
        items = [dict(job, job_id=job_id) for job_id, job in _jobs.items()]

    for item in items:
        if item.get("secret") and item["status"] in ("done", "error"):
            item["result"] = None

    items.sort(key=lambda j: j["started_at"], reverse=True)
    return items


def running_jobs_count():
    """Cheap count for the always-visible header chip -- no need to build the full list just to show a number."""
    with _lock:
        return sum(1 for job in _jobs.values() if job["status"] == "running")


def consume_job_result(job_id):
    """
    For a secret job only: returns the job's full state (including its real
    result) exactly once, then deletes it from the registry so it cannot be
    read again by anyone -- bounds a found password/seed phrase's exposure
    window to a single read. Non-secret jobs are returned as-is (get_job()
    already exposes their result freely; nothing to protect).

    :return: a copy of the job's state, or None if unknown/already consumed.
    """
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        copy = dict(job)
        if job.get("secret"):
            del _jobs[job_id]
        return copy
