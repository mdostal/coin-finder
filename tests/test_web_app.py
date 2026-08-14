import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_create_app_rejects_non_loopback_host():
    with pytest.raises(RuntimeError):
        create_app(host="0.0.0.0")


def test_create_app_accepts_localhost():
    create_app(host="localhost")


def test_index_page_loads(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_unknown_job_returns_404(client):
    resp = client.get("/api/jobs/does-not-exist")
    assert resp.status_code == 404


def test_unknown_job_scan_page_returns_404(client):
    resp = client.get("/scan/does-not-exist")
    assert resp.status_code == 404


def test_browse_endpoint_errors_on_missing_path(client, tmp_path):
    resp = client.get("/api/browse", query_string={"path": str(tmp_path / "nope")})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_browse_endpoint_lists_subdirectories_only(client, tmp_path):
    (tmp_path / "sub1").mkdir()
    (tmp_path / "sub2").mkdir()
    (tmp_path / "afile.txt").write_text("x")

    resp = client.get("/api/browse", query_string={"path": str(tmp_path)})
    assert resp.status_code == 200
    data = resp.get_json()
    assert sorted(data["subdirectories"]) == sorted(
        [str(tmp_path / "sub1"), str(tmp_path / "sub2")]
    )


def test_scan_rejects_nonexistent_directory(client):
    resp = client.post("/scan", data={"input_dir": "/definitely/not/a/real/dir"})
    assert resp.status_code == 400


@patch("web.app.scan_for_hidden_volumes")
@patch("web.app.run_pipeline")
def test_scan_job_lifecycle_reaches_done(mock_pipeline, mock_hidden, client, tmp_path):
    mock_pipeline.main.return_value = None
    mock_hidden.return_value = []

    resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
    assert resp.status_code == 302
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]

    job = None
    for _ in range(100):
        status_resp = client.get(f"/api/jobs/{job_id}")
        assert status_resp.status_code == 200
        job = status_resp.get_json()
        if job["status"] != "running":
            break
        time.sleep(0.05)

    assert job["status"] == "done"
    mock_pipeline.main.assert_called_once()
    mock_hidden.assert_called_once_with(str(tmp_path))


@patch("web.app.record_finding")
@patch("web.app.scan_for_hidden_volumes")
@patch("web.app.run_pipeline")
def test_scan_job_records_balances_into_the_findings_store(mock_pipeline, mock_hidden, mock_record, client, tmp_path):
    balances_data = {"walletA.dat": {"Bitcoin": {"1abc": 0.5}}}

    def fake_main(input_dir, output_dir, progress_callback=None):
        checks_dir = Path(output_dir) / "checks"
        checks_dir.mkdir(parents=True, exist_ok=True)
        with open(checks_dir / "wallet_balances.json", "w") as f:
            json.dump(balances_data, f)

    mock_pipeline.main.side_effect = fake_main
    mock_hidden.return_value = []

    resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]

    job = None
    for _ in range(100):
        status_resp = client.get(f"/api/jobs/{job_id}")
        job = status_resp.get_json()
        if job["status"] != "running":
            break
        time.sleep(0.05)

    assert job["status"] == "done"
    mock_record.assert_called_once_with("Bitcoin", "1abc", 0.5, source_path="walletA.dat", source_label="scan")


@patch("web.app.scan_for_hidden_volumes")
@patch("web.app.run_pipeline")
def test_scan_job_progress_flows_through_to_the_job_status(mock_pipeline, mock_hidden, client, tmp_path):
    def fake_main(input_dir, output_dir, progress_callback=None):
        progress_callback(5, 10, "checking addresses")

    mock_pipeline.main.side_effect = fake_main
    mock_hidden.return_value = []

    resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]

    job = None
    for _ in range(100):
        status_resp = client.get(f"/api/jobs/{job_id}")
        job = status_resp.get_json()
        if job["status"] != "running":
            break
        time.sleep(0.05)

    assert job["status"] == "done"
    assert job["progress"] == {"current": 5, "total": 10, "message": "checking addresses"}


@patch("web.app.scan_for_hidden_volumes")
@patch("web.app.run_pipeline")
def test_scan_status_page_renders_once_done(mock_pipeline, mock_hidden, client, tmp_path):
    mock_pipeline.main.return_value = None
    mock_hidden.return_value = []

    resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]

    for _ in range(100):
        status_resp = client.get(f"/api/jobs/{job_id}")
        if status_resp.get_json()["status"] != "running":
            break
        time.sleep(0.05)

    page_resp = client.get(f"/scan/{job_id}")
    assert page_resp.status_code == 200


@patch("web.app.scan_for_hidden_volumes")
@patch("web.app.run_pipeline")
def test_scan_job_error_is_reported_not_raised(mock_pipeline, mock_hidden, client, tmp_path):
    mock_pipeline.main.side_effect = RuntimeError("boom")
    mock_hidden.return_value = []

    resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]

    job = None
    for _ in range(100):
        status_resp = client.get(f"/api/jobs/{job_id}")
        job = status_resp.get_json()
        if job["status"] != "running":
            break
        time.sleep(0.05)

    assert job["status"] == "error"
    assert "boom" in job["error"]
