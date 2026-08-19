import threading

from tools.checkpoint_store import CheckpointPaused
from web import jobs_store

# sse-04: this module used to own an in-memory dict (_jobs = {}), wiped on
# every app restart. It now delegates every state mutation/read to
# web/jobs_store.py's sqlite-backed table -- create_job/start_job/
# report_progress/get_job keep the exact same call signatures every
# existing web/app.py call site already uses, so no caller needed to
# change. This module still owns the one thing that was never about
# storage: actually running fn() in a background thread.


def create_job(secret=False, kind="job", label=None, checkpoint_path=None):
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
    :param checkpoint_path: optional -- the sqlite checkpoint file (see
        tools.checkpoint_store.CheckpointStore) the wrapped stage function
        opens, if this job wraps a checkpoint-backed stage (search,
        analyze, check-balances). None (the default) for every other job
        kind -- and for existing callers, which don't pass this at all.
        Recorded so a later POST /jobs/<job_id>/pause can find it without
        needing to know which stage this job wraps.
    """
    return jobs_store.create_job(secret=secret, kind=kind, label=label, checkpoint_path=checkpoint_path)


def start_job(job_id, fn, *args, **kwargs):
    """Runs fn(*args, **kwargs) in a background daemon thread for an already-created job_id (see create_job())."""

    def _target():
        try:
            result = fn(*args, **kwargs)
            jobs_store.update_status(job_id, "done", result=result)
        except CheckpointPaused:
            # A checkpoint-backed stage noticed a pause request and
            # stopped cleanly (in-flight work already finished, progress
            # already flushed) -- this is not an error. "paused" is a
            # resumable status: re-dispatching the same stage function
            # against the same checkpoint_path picks up where it left
            # off, identical to today's crash-resume, just user-triggered.
            jobs_store.update_status(job_id, "paused")
        except Exception as e:
            jobs_store.update_status(job_id, "error", error=str(e))

    threading.Thread(target=_target, daemon=True).start()


def run_job(fn, *args, secret=False, kind="job", label=None, checkpoint_path=None, **kwargs):
    """
    Start fn(*args, **kwargs) in a background daemon thread, tracked in a
    durable sqlite-backed registry (web/jobs_store.py). Single local user,
    one-scan-at-a-time is the realistic usage pattern; nothing here
    prevents running several jobs concurrently against different inputs.

    :param secret: True for jobs whose result may itself be sensitive (e.g.
        an unlock attempt's found password). Secret job results are hidden
        from get_job()/the polling API entirely -- only consume_job_result()
        can read one, exactly once, before it is deleted from the registry.
    :param kind: see create_job().
    :param label: see create_job().
    :param checkpoint_path: see create_job().
    :return: job_id (str) usable with get_job().
    """
    job_id = create_job(secret=secret, kind=kind, label=label, checkpoint_path=checkpoint_path)
    start_job(job_id, fn, *args, **kwargs)
    return job_id


def report_progress(job_id, current, total, message=""):
    """
    Updates a running job's progress -- called mid-execution by a tool's
    progress_callback. Silently a no-op for an unknown job_id (a job that
    already finished, or was never started) rather than raising, since a
    background thread calling this has no good way to handle that error.
    """
    jobs_store.update_progress(job_id, current, total, message)


def get_job(job_id):
    """
    :return: a copy of the job's current state dict, or None if unknown.
        For a secret job in a terminal state (done/error), "result" is
        stripped from the copy -- this is the path polled repeatedly by the
        frontend, so a secret-bearing result must never be readable here,
        only via consume_job_result().
    """
    job = jobs_store.get_job(job_id)
    if job is None:
        return None
    if job.get("secret") and job["status"] in ("done", "error"):
        job["result"] = None
    return job


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
    items = jobs_store.list_jobs()
    for item in items:
        if item.get("secret") and item["status"] in ("done", "error"):
            item["result"] = None
    return items


def running_jobs_count():
    """Cheap count for the always-visible header chip -- no need to build the full list just to show a number."""
    return jobs_store.running_jobs_count()


def consume_job_result(job_id):
    """
    For a secret job only: returns the job's full state (including its real
    result) exactly once, then deletes it from the registry so it cannot be
    read again by anyone -- bounds a found password/seed phrase's exposure
    window to a single read. Non-secret jobs are returned as-is (get_job()
    already exposes their result freely; nothing to protect).

    :return: a copy of the job's state, or None if unknown/already consumed.
    """
    job = jobs_store.get_job(job_id)
    if job is None:
        return None
    if job.get("secret"):
        jobs_store.delete_job(job_id)
    return job
