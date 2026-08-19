from unittest.mock import patch

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _job(job_id="abc", kind="find", label="/data/drive1", status="running", checkpoint_path="/out/checks/scan_checkpoint.db"):
    return {
        "job_id": job_id,
        "kind": kind,
        "label": label,
        "status": status,
        "started_at": 0.0,
        "secret": False,
        "checkpoint_path": checkpoint_path,
        "progress": None,
        "result": None,
        "error": None,
    }


# --- POST /jobs/<job_id>/pause ------------------------------------------------


@patch("web.app.request_pause_for")
@patch("web.app.get_job")
def test_pause_route_pauses_both_checkpoints_for_a_running_find_job(mock_get_job, mock_pause, client):
    """A "find" job wraps search + analyze -- only whichever stage is
    actually running has a checkpoint file that exists on disk, so both
    sibling paths get touched (request_pause_for is a safe no-op against
    the one that doesn't exist yet/anymore)."""
    mock_get_job.return_value = _job(status="running", checkpoint_path="/out/checks/scan_checkpoint.db")

    resp = client.post("/jobs/abc/pause", follow_redirects=False)

    assert resp.status_code == 302
    paused_paths = [c.args[0] for c in mock_pause.call_args_list]
    assert "/out/checks/scan_checkpoint.db" in paused_paths
    assert "/out/checks/analyze_checkpoint.db" in paused_paths


@patch("web.app.request_pause_for")
@patch("web.app.get_job")
def test_pause_route_check_balances_job_touches_only_its_own_checkpoint(mock_get_job, mock_pause, client):
    mock_get_job.return_value = _job(kind="check-balances", checkpoint_path="/out/checks/balance_checkpoint.db")

    client.post("/jobs/abc/pause")

    paused_paths = [c.args[0] for c in mock_pause.call_args_list]
    assert paused_paths == ["/out/checks/balance_checkpoint.db"]


@patch("web.app.request_pause_for")
@patch("web.app.get_job")
def test_pause_route_is_a_noop_for_a_job_that_is_not_running(mock_get_job, mock_pause, client):
    mock_get_job.return_value = _job(status="done")

    resp = client.post("/jobs/abc/pause")

    assert resp.status_code == 302
    mock_pause.assert_not_called()


@patch("web.app.request_pause_for")
@patch("web.app.get_job")
def test_pause_route_is_a_noop_for_a_job_with_no_checkpoint(mock_get_job, mock_pause, client):
    """Jobs this story doesn't cover (unlock, crawl, drive-scan, ...)
    have no checkpoint_path at all -- pausing must not error."""
    mock_get_job.return_value = _job(kind="crawl", checkpoint_path=None)

    resp = client.post("/jobs/abc/pause")

    assert resp.status_code == 302
    mock_pause.assert_not_called()


@patch("web.app.get_job")
def test_pause_route_404s_for_an_unknown_job(mock_get_job, client):
    mock_get_job.return_value = None

    resp = client.post("/jobs/nope/pause")

    assert resp.status_code == 404


# --- POST /jobs/<job_id>/resume -----------------------------------------------


@patch("web.app.start_job")
@patch("web.app.create_job")
@patch("web.app.clear_pause_for")
@patch("web.app.get_job")
def test_resume_route_clears_pause_and_redispatches_a_find_job(mock_get_job, mock_clear, mock_create, mock_start, client):
    mock_get_job.return_value = _job(
        status="paused", kind="find", label="/data/drive1", checkpoint_path="/out/checks/scan_checkpoint.db"
    )
    mock_create.return_value = "new-job-id"

    resp = client.post("/jobs/abc/resume", follow_redirects=False)

    assert resp.status_code == 302
    cleared_paths = [c.args[0] for c in mock_clear.call_args_list]
    assert "/out/checks/scan_checkpoint.db" in cleared_paths
    assert "/out/checks/analyze_checkpoint.db" in cleared_paths
    mock_create.assert_called_once_with(kind="find", label="/data/drive1", checkpoint_path="/out/checks/scan_checkpoint.db")
    assert mock_start.call_args.args[0] == "new-job-id"
    assert resp.headers["Location"].rstrip("/").endswith("/scan/new-job-id")  # redirected to the new job's own status page


@patch("web.app.start_job")
@patch("web.app.create_job")
@patch("web.app.clear_pause_for")
@patch("web.app.get_job")
def test_resume_route_redispatches_a_check_balances_job_with_derived_output_dir(
    mock_get_job, mock_clear, mock_create, mock_start, client
):
    mock_get_job.return_value = _job(
        status="paused", kind="check-balances", label="/data/drive1", checkpoint_path="/out/checks/balance_checkpoint.db"
    )
    mock_create.return_value = "new-job-id"

    resp = client.post("/jobs/abc/resume", follow_redirects=False)

    assert resp.status_code == 302
    mock_create.assert_called_once_with(
        kind="check-balances", label="/data/drive1", checkpoint_path="/out/checks/balance_checkpoint.db"
    )
    args = mock_start.call_args.args
    assert args[0] == "new-job-id"
    assert args[2] == "/out"  # output_dir derived from checkpoint_path.parent.parent


@patch("web.app.get_job")
def test_resume_route_404s_for_a_job_that_is_not_paused(mock_get_job, client):
    mock_get_job.return_value = _job(status="running")

    resp = client.post("/jobs/abc/resume")

    assert resp.status_code == 404


@patch("web.app.get_job")
def test_resume_route_404s_for_an_unknown_job(mock_get_job, client):
    mock_get_job.return_value = None

    resp = client.post("/jobs/nope/resume")

    assert resp.status_code == 404


# --- jobs.html UI --------------------------------------------------------------


@patch("web.app.list_jobs")
def test_jobs_page_shows_pause_button_for_a_running_checkpointed_job(mock_list, client):
    mock_list.return_value = [_job(status="running")]

    resp = client.get("/jobs")

    assert resp.status_code == 200
    assert b"/jobs/abc/pause" in resp.data
    assert b"Pause" in resp.data


@patch("web.app.list_jobs")
def test_jobs_page_shows_resume_button_for_a_paused_job(mock_list, client):
    mock_list.return_value = [_job(status="paused")]

    resp = client.get("/jobs")

    assert resp.status_code == 200
    assert b"/jobs/abc/resume" in resp.data
    assert b"Resume" in resp.data


@patch("web.app.list_jobs")
def test_jobs_page_hides_pause_button_for_a_job_with_no_checkpoint(mock_list, client):
    mock_list.return_value = [_job(kind="crawl", status="running", checkpoint_path=None)]

    resp = client.get("/jobs")

    assert resp.status_code == 200
    assert b"/jobs/abc/pause" not in resp.data
