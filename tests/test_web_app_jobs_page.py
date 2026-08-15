from unittest.mock import patch

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@patch("web.app.list_jobs")
def test_jobs_page_loads_and_shows_kind_and_label(mock_list, client):
    mock_list.return_value = [
        {"job_id": "abc", "kind": "scan", "label": "/Volumes/OldDrive", "status": "running", "started_at": 0, "secret": False}
    ]

    resp = client.get("/jobs")

    assert resp.status_code == 200
    assert b"scan" in resp.data
    assert b"/Volumes/OldDrive" in resp.data


@patch("web.app.list_jobs")
def test_jobs_page_empty_state(mock_list, client):
    mock_list.return_value = []

    resp = client.get("/jobs")

    assert resp.status_code == 200
    assert b"No jobs yet" in resp.data


def test_jobs_page_links_scan_kind_to_scan_status(client, tmp_path):
    wallet_dir = tmp_path
    resp = client.post("/scan", data={"input_dir": str(wallet_dir)}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]

    jobs_resp = client.get("/jobs")

    assert f"/scan/{job_id}".encode() in jobs_resp.data
