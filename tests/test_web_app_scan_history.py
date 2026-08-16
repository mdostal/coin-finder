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


def _wait_for_done(client, job_id):
    job = None
    for _ in range(100):
        resp = client.get(f"/api/jobs/{job_id}")
        job = resp.get_json()
        if job["status"] != "running":
            break
        time.sleep(0.05)
    return job


@patch("web.app.record_scan")
def test_start_scan_writes_find_summary_json_to_disk(mock_record_scan, client, tmp_path):
    (tmp_path / "a.dat").write_text("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")

    resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    job = _wait_for_done(client, job_id)
    assert job["status"] == "done"

    output_dir = Path(job["result"]["output_dir"])
    summary_path = output_dir / "find_summary.json"
    assert summary_path.exists()
    with open(summary_path) as f:
        on_disk = json.load(f)
    assert on_disk == job["result"]


@patch("web.app.record_scan")
def test_start_scan_records_scan_history_entry(mock_record_scan, client, tmp_path):
    (tmp_path / "a.dat").write_text("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")

    resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    job = _wait_for_done(client, job_id)

    mock_record_scan.assert_called_once_with(str(tmp_path), job["result"]["output_dir"], job["result"]["files_found"])
