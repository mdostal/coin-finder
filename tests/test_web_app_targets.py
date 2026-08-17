import time
from unittest.mock import patch

import pytest

from web.app import create_app


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


@patch("web.app.list_mounted_volumes")
@patch("web.app.list_targets")
def test_targets_page_loads(mock_list_targets, mock_list_volumes, client):
    mock_list_targets.return_value = [{"label": "A", "path": "/a", "kind": "local", "added_at": 0}]
    mock_list_volumes.return_value = [{"name": "OldDrive", "path": "/Volumes/OldDrive", "is_bound": False}]

    resp = client.get("/targets")

    assert resp.status_code == 200


@patch("web.app.add_target")
def test_targets_add_calls_add_target(mock_add, client, tmp_path):
    resp = client.post("/targets/add", data={"label": "Old Drive", "path": str(tmp_path), "kind": "volume"}, follow_redirects=False)

    assert resp.status_code == 302
    mock_add.assert_called_once_with("Old Drive", str(tmp_path), "volume")


@patch("web.app.remove_target")
def test_targets_remove_calls_remove_target(mock_remove, client):
    resp = client.post("/targets/remove", data={"label": "Old Drive"}, follow_redirects=False)

    assert resp.status_code == 302
    mock_remove.assert_called_once_with("Old Drive")


def test_targets_add_rejects_missing_path(client):
    resp = client.post("/targets/add", data={"label": "X", "path": "", "kind": "local"})
    assert resp.status_code == 400


@patch("web.app.list_excludes")
@patch("web.app.list_mounted_volumes")
@patch("web.app.list_targets")
def test_targets_page_shows_excludes(mock_list_targets, mock_list_volumes, mock_list_excludes, client):
    mock_list_targets.return_value = []
    mock_list_volumes.return_value = []
    mock_list_excludes.return_value = [{"path": "/Volumes/OldDrive/junk", "added_at": 0}]

    resp = client.get("/targets")

    assert resp.status_code == 200
    assert b"/Volumes/OldDrive/junk" in resp.data


@patch("web.app.add_exclude")
def test_targets_excludes_add_calls_add_exclude(mock_add, client, tmp_path):
    resp = client.post("/targets/excludes/add", data={"path": str(tmp_path)}, follow_redirects=False)

    assert resp.status_code == 302
    mock_add.assert_called_once_with(str(tmp_path))


def test_targets_excludes_add_rejects_missing_path(client):
    resp = client.post("/targets/excludes/add", data={"path": ""})
    assert resp.status_code == 400


@patch("web.app.remove_exclude")
def test_targets_excludes_remove_calls_remove_exclude(mock_remove, client):
    resp = client.post("/targets/excludes/remove", data={"path": "/a"}, follow_redirects=False)

    assert resp.status_code == 302
    mock_remove.assert_called_once_with("/a")


@patch("web.app.list_excludes")
@patch("web.app.scan_for_hidden_volumes", return_value=[])
@patch("web.app.run_pipeline")
def test_scan_passes_configured_excludes_through_to_find(mock_pipeline, mock_hidden, mock_list_excludes, client, tmp_path):
    mock_list_excludes.return_value = [{"path": "/Volumes/OldDrive/junk", "added_at": 0}]
    mock_pipeline.find.return_value = {"output_dir": str(tmp_path / "out"), "files_found": 0, "coin_counts": {}, "total_address_instances": 0}

    resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
    assert resp.status_code == 302
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    _wait_for_terminal(client, job_id)

    mock_pipeline.find.assert_called_once()
    assert mock_pipeline.find.call_args.kwargs["excludes"] == ["/Volumes/OldDrive/junk"]
