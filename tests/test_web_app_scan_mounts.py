import threading
import time
from unittest.mock import patch

import pytest

from web.app import create_app
from web.jobs import list_jobs


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _wait_for_terminal(client, job_id, timeout_iterations=100):
    job = None
    for _ in range(timeout_iterations):
        resp = client.get(f"/api/jobs/{job_id}")
        job = resp.get_json()
        if job["status"] != "running":
            break
        time.sleep(0.05)
    return job


@patch("web.app.list_mounts")
def test_index_shows_currently_mounted_drives_only(mock_list_mounts, client):
    mock_list_mounts.return_value = [
        {"remote_name": "gdrive", "mount_point": "/mnt/gdrive", "started_at": 0, "is_mounted": True, "log_path": None},
        {"remote_name": "stale", "mount_point": "/mnt/stale", "started_at": 0, "is_mounted": False, "log_path": None},
    ]

    resp = client.get("/")

    assert resp.status_code == 200
    assert b"/mnt/gdrive" in resp.data
    assert b"/mnt/stale" not in resp.data


@patch("web.app.list_mounts", return_value=[])
def test_index_hides_mounted_drives_card_when_nothing_is_mounted(mock_list_mounts, client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Scan mounted drives" not in resp.data


def test_start_scan_mounts_requires_at_least_one_selection(client):
    resp = client.post("/scan/mounts", data={})
    assert resp.status_code == 400
    assert b"Select at least one" in resp.data


def test_start_scan_mounts_rejects_a_mount_point_that_is_not_a_real_directory(client):
    resp = client.post("/scan/mounts", data={"mount_points": ["/not/a/real/path"]})
    assert resp.status_code == 400
    assert b"Not a directory" in resp.data


@patch("web.app.scan_for_hidden_volumes", return_value=[])
@patch("web.app.run_pipeline")
def test_start_scan_returns_existing_job_instead_of_duplicating_when_already_running(mock_pipeline, mock_hidden, client, tmp_path):
    """
    Regression test for a real bug hit live: nothing stopped the same
    directory (a slow cloud-mounted drive, in the real report) from
    getting scanned by two concurrent `find` jobs at once -- observed
    firsthand as two "running" rows on /jobs for the identical target,
    ~20 seconds apart, most likely from clicking "Resume" on the
    interrupted-scan banner more than once. A second request for a
    directory that already has a running find job must redirect to that
    same job, not start a duplicate.
    """
    target = tmp_path / "gdrive-mount"
    target.mkdir()
    release_first_job = threading.Event()

    def _blocking_find(*args, **kwargs):
        release_first_job.wait(timeout=5)
        return {"output_dir": str(tmp_path / "out"), "files_found": 0, "coin_counts": {}, "total_address_instances": 0}

    mock_pipeline.find.side_effect = _blocking_find

    first_resp = client.post("/scan", data={"input_dir": str(target)}, follow_redirects=False)
    assert first_resp.status_code == 302
    first_job_id = first_resp.headers["Location"].rsplit("/", 1)[-1]

    second_resp = client.post("/scan", data={"input_dir": str(target)}, follow_redirects=False)
    assert second_resp.status_code == 302
    second_job_id = second_resp.headers["Location"].rsplit("/", 1)[-1]

    assert second_job_id == first_job_id

    running_find_jobs = [j for j in list_jobs() if j["kind"] == "find" and j["label"] == str(target)]
    assert len(running_find_jobs) == 1

    release_first_job.set()
    _wait_for_terminal(client, first_job_id)


@patch("web.app.scan_for_hidden_volumes", return_value=[])
@patch("web.app.run_pipeline")
def test_start_scan_mounts_starts_one_job_per_selected_mount(mock_pipeline, mock_hidden, client, tmp_path):
    mount_a = tmp_path / "mount_a"
    mount_a.mkdir()
    mount_b = tmp_path / "mount_b"
    mount_b.mkdir()
    mock_pipeline.find.return_value = {"output_dir": str(tmp_path / "out"), "files_found": 0, "coin_counts": {}, "total_address_instances": 0}

    resp = client.post("/scan/mounts", data={"mount_points": [str(mount_a), str(mount_b)]}, follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/jobs")

    jobs_resp = client.get("/jobs")
    assert str(mount_a).encode() in jobs_resp.data
    assert str(mount_b).encode() in jobs_resp.data


@patch("web.app.scan_for_hidden_volumes", return_value=[])
@patch("web.app.run_pipeline")
def test_start_scan_mounts_jobs_run_concurrently_not_serially(mock_pipeline, mock_hidden, client, tmp_path):
    """
    The real point of "scan multiple mounts at once": both jobs should be
    running at the same time, not one waiting for the other to finish --
    proven the same way test_different_coins_are_checked_concurrently
    proves it, by having each job block until the other has started.
    """
    import threading

    mount_a = tmp_path / "mount_a"
    mount_a.mkdir()
    mount_b = tmp_path / "mount_b"
    mount_b.mkdir()

    a_started = threading.Event()
    b_started = threading.Event()
    started_by_dir = {str(mount_a): a_started, str(mount_b): b_started}
    other_by_dir = {str(mount_a): b_started, str(mount_b): a_started}

    def fake_find(input_dir, out_dir, index_db_path=None, checkpoint_path=None, progress_callback=None, excludes=None):
        started_by_dir[input_dir].set()
        assert other_by_dir[input_dir].wait(timeout=2), "the other mount's scan never started -- mounts are being scanned serially"
        return {"output_dir": out_dir, "files_found": 0, "coin_counts": {}, "total_address_instances": 0}

    mock_pipeline.find.side_effect = fake_find

    resp = client.post("/scan/mounts", data={"mount_points": [str(mount_a), str(mount_b)]}, follow_redirects=False)
    assert resp.status_code == 302

    jobs = {j["label"]: j["job_id"] for j in list_jobs()}
    for job_id in (jobs[str(mount_a)], jobs[str(mount_b)]):
        job = _wait_for_terminal(client, job_id)
        assert job["status"] == "done", job.get("error")  # "error" here means the rendezvous timed out -- serial, not concurrent


@patch("web.app.scan_for_hidden_volumes", return_value=[])
@patch("web.app.run_pipeline")
def test_start_scan_mounts_skips_mount_points_that_already_have_a_running_job(mock_pipeline, mock_hidden, client, tmp_path):
    target = tmp_path / "mount_a"
    target.mkdir()
    release_first_job = threading.Event()

    def _blocking_find(*args, **kwargs):
        release_first_job.wait(timeout=5)
        return {"output_dir": str(tmp_path / "out"), "files_found": 0, "coin_counts": {}, "total_address_instances": 0}

    mock_pipeline.find.side_effect = _blocking_find

    client.post("/scan/mounts", data={"mount_points": [str(target)]}, follow_redirects=False)
    client.post("/scan/mounts", data={"mount_points": [str(target)]}, follow_redirects=False)

    running_find_jobs = [j for j in list_jobs() if j["kind"] == "find" and j["label"] == str(target)]
    assert len(running_find_jobs) == 1

    release_first_job.set()
    _wait_for_terminal(client, running_find_jobs[0]["job_id"])
