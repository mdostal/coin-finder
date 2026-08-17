import json
import time
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


def _start_find_job(client, tmp_path, files):
    """Runs a real find() against a tmp_path directory containing `files`
    ({filename: content}), returning (job_id, output_dir)."""
    for name, content in files.items():
        (tmp_path / name).write_text(content)

    resp = client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    job = _wait_for_done(client, job_id)
    assert job["status"] == "done"
    return job_id, job["result"]["output_dir"]


def test_check_balances_selected_requires_at_least_one_file(client, tmp_path):
    job_id, _ = _start_find_job(client, tmp_path, {"a.dat": "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"})
    resp = client.post(f"/scan/{job_id}/check-balances-selected", data={})
    assert resp.status_code == 400


def test_check_balances_selected_404s_for_unknown_job(client):
    resp = client.post("/scan/does-not-exist/check-balances-selected", data={"files": "a.dat"})
    assert resp.status_code == 404


@patch("web.app.check_wallet_balances")
def test_check_balances_selected_only_checks_chosen_files(mock_check, client, tmp_path):
    job_id, output_dir = _start_find_job(
        client,
        tmp_path,
        {"a.dat": "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2", "b.dat": "1FfmbHfnpaZjKFvyi1okTjJJusN455paPH"},
    )
    mock_check.return_value = {}

    selected_path = str(tmp_path / "a.dat")
    resp = client.post(f"/scan/{job_id}/check-balances-selected", data={"files": selected_path}, follow_redirects=False)
    assert resp.status_code == 302
    balances_job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    _wait_for_done(client, balances_job_id)

    input_file_arg = mock_check.call_args[0][0]
    with open(input_file_arg) as f:
        subset = json.load(f)
    assert list(subset.keys()) == [selected_path]


@patch("web.app.record_finding")
@patch("web.app.check_wallet_balances")
def test_check_balances_selected_records_findings(mock_check, mock_record, client, tmp_path):
    job_id, output_dir = _start_find_job(client, tmp_path, {"a.dat": "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"})
    selected_path = str(tmp_path / "a.dat")

    def fake_check(input_file, output_file, progress_callback=None):
        with open(output_file, "w") as f:
            json.dump({selected_path: {"Bitcoin": {"1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2": 0.5}}}, f)

    mock_check.side_effect = fake_check

    resp = client.post(f"/scan/{job_id}/check-balances-selected", data={"files": selected_path}, follow_redirects=False)
    balances_job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    _wait_for_done(client, balances_job_id)

    mock_record.assert_called_once_with("Bitcoin", "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2", 0.5, source_path=selected_path, source_label="scan")


@patch("web.app.record_finding")
@patch("web.app.check_wallet_balances")
def test_check_balances_selected_never_touches_the_full_scans_own_output(mock_check, mock_record, client, tmp_path):
    """The real risk called out in design-discussion.md §3: a selective
    run must never overwrite output_dir/checks/wallet_balances.json --
    that file belongs to the whole-scan flow and may hold results for
    files not in this selection."""
    job_id, output_dir = _start_find_job(client, tmp_path, {"a.dat": "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"})
    from pathlib import Path

    full_balances_path = Path(output_dir) / "checks" / "wallet_balances.json"
    full_balances_path.parent.mkdir(parents=True, exist_ok=True)
    full_balances_path.write_text('{"sentinel": "do not touch"}')
    before = full_balances_path.read_text()

    def fake_check(input_file, output_file, progress_callback=None):
        with open(output_file, "w") as f:
            json.dump({}, f)

    mock_check.side_effect = fake_check

    selected_path = str(tmp_path / "a.dat")
    resp = client.post(f"/scan/{job_id}/check-balances-selected", data={"files": selected_path}, follow_redirects=False)
    balances_job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    _wait_for_done(client, balances_job_id)

    assert full_balances_path.read_text() == before


@patch("web.app.check_wallet_balances")
def test_check_balances_selected_redirects_to_existing_results_page(mock_check, client, tmp_path):
    job_id, output_dir = _start_find_job(client, tmp_path, {"a.dat": "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"})
    mock_check.return_value = {}

    resp = client.post(f"/scan/{job_id}/check-balances-selected", data={"files": str(tmp_path / "a.dat")}, follow_redirects=False)
    assert "/scan/balances/" in resp.headers["Location"]
