import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from web.app import create_app
from web.scan_history import clear_scan_history as real_clear_scan_history
from web.scan_history import list_scan_history as real_list_scan_history
from web.scan_history import record_scan as real_record_scan


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


def _start_find_job(client, tmp_path, files):
    for name, content in files.items():
        (tmp_path / name).write_text(content)

    resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    job = _wait_for_done(client, job_id)
    assert job["status"] == "done"
    return job_id, job["result"]["output_dir"]


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


def test_scans_page_empty_state(client):
    with patch("web.app.list_scan_history", return_value=[]):
        resp = client.get("/scans")
    assert resp.status_code == 200


def test_scans_page_lists_recorded_scan(client, tmp_path):
    db_path = tmp_path / "scan_history.db"

    def fake_record(input_dir, output_dir, files_found):
        real_record_scan(input_dir, output_dir, files_found, db_path=db_path)

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    with patch("web.app.record_scan", side_effect=fake_record):
        _start_find_job(client, input_dir, {"a.dat": "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"})

    with patch("web.app.list_scan_history", side_effect=lambda: real_list_scan_history(db_path=db_path)):
        resp = client.get("/scans")
    assert resp.status_code == 200
    assert str(input_dir).encode() in resp.data


def test_scans_clear_empties_the_list(client, tmp_path):
    with patch("web.app.clear_scan_history") as mock_clear:
        resp = client.post("/scans/clear", follow_redirects=False)
    assert resp.status_code == 302
    mock_clear.assert_called_once()


def test_scan_view_shows_find_summary_for_completed_scan(client, tmp_path):
    with patch("web.app.record_scan"):
        job_id, output_dir = _start_find_job(client, tmp_path, {"a.dat": "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"})

    resp = client.get("/scans/view", query_string={"output_dir": output_dir})
    assert resp.status_code == 200
    assert b"a.dat" in resp.data


def test_scan_view_404s_when_find_summary_missing(client, tmp_path):
    resp = client.get("/scans/view", query_string={"output_dir": str(tmp_path)})
    assert resp.status_code == 404


def test_scan_view_404s_with_no_output_dir(client):
    resp = client.get("/scans/view")
    assert resp.status_code == 404


@patch("web.app.record_finding")
@patch("web.app.check_wallet_balances")
def test_check_balances_selected_from_durable_view(mock_check, mock_record, client, tmp_path):
    with patch("web.app.record_scan"):
        job_id, output_dir = _start_find_job(client, tmp_path, {"a.dat": "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"})
    mock_check.return_value = {}

    selected_path = str(tmp_path / "a.dat")
    resp = client.post(
        "/scans/view/check-balances-selected",
        data={"output_dir": output_dir, "files": selected_path},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/scan/balances/" in resp.headers["Location"]
    balances_job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    _wait_for_done(client, balances_job_id)

    input_file_arg = mock_check.call_args[0][0]
    with open(input_file_arg) as f:
        subset = json.load(f)
    assert list(subset.keys()) == [selected_path]


def test_check_balances_selected_from_durable_view_requires_a_file(client, tmp_path):
    with patch("web.app.record_scan"):
        job_id, output_dir = _start_find_job(client, tmp_path, {"a.dat": "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"})

    resp = client.post("/scans/view/check-balances-selected", data={"output_dir": output_dir}, follow_redirects=False)
    assert resp.status_code == 400


def test_check_balances_selected_from_durable_view_404s_for_unknown_output_dir(client):
    resp = client.post("/scans/view/check-balances-selected", data={"output_dir": "/nope", "files": "a.dat"}, follow_redirects=False)
    assert resp.status_code == 404


@patch("web.app.check_wallet_balances")
def test_check_balances_from_durable_view(mock_check, client, tmp_path):
    with patch("web.app.record_scan"):
        job_id, output_dir = _start_find_job(client, tmp_path, {"a.dat": "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"})
    mock_check.return_value = {}

    resp = client.post("/scans/view/check-balances", data={"output_dir": output_dir}, follow_redirects=False)
    assert resp.status_code == 302
    assert "/scan/balances/" in resp.headers["Location"]


def test_check_balances_from_durable_view_404s_for_unknown_output_dir(client):
    resp = client.post("/scans/view/check-balances", data={"output_dir": "/nope"}, follow_redirects=False)
    assert resp.status_code == 404
