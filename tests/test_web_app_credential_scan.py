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


def _job_id_from_redirect(resp):
    return resp.headers["Location"].rstrip("/").split("/")[-1]


@patch("web.app.credential_status_index")
@patch("web.app.run_credential_scan")
@patch("web.app.list_findings")
def test_check_credential_status_starts_a_background_job_scoped_to_selected_wallets(
    mock_list, mock_run_scan, mock_status_index, client, tmp_path
):
    wallet_a = tmp_path / "a.dat"
    wallet_a.write_bytes(b"x")
    wallet_b = tmp_path / "b.dat"
    wallet_b.write_bytes(b"x")
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1a", "source_path": str(wallet_a), "status": "new"},
        {"coin": "Bitcoin", "address": "1b", "source_path": str(wallet_b), "status": "new"},
    ]
    mock_run_scan.return_value = {"report": "ok", "results": []}

    resp = client.post("/findings/check-credential-status", data={"wallet_paths": str(wallet_a)}, follow_redirects=False)

    assert resp.status_code == 302
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_terminal(client, job_id)
    assert job["status"] == "done"
    mock_run_scan.assert_called_once_with([str(wallet_a)])


@patch("web.app.credential_status_index")
@patch("web.app.list_findings", return_value=[])
def test_check_credential_status_no_selection_redirects_without_starting_a_job(mock_list, mock_status_index, client):
    resp = client.post("/findings/check-credential-status", data={}, follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["Location"].rstrip("/").endswith("/findings")


@patch("web.app.credential_status_index")
@patch("web.app.run_credential_scan")
@patch("web.app.list_findings")
def test_check_credential_status_ignores_paths_that_are_not_known_findings(
    mock_list, mock_run_scan, mock_status_index, client, tmp_path
):
    known_wallet = tmp_path / "known.dat"
    known_wallet.write_bytes(b"x")
    unknown_wallet = tmp_path / "unknown.dat"
    unknown_wallet.write_bytes(b"x")
    mock_list.return_value = [{"coin": "Bitcoin", "address": "1a", "source_path": str(known_wallet), "status": "new"}]
    mock_run_scan.return_value = {"report": "ok", "results": []}

    resp = client.post(
        "/findings/check-credential-status",
        data={"wallet_paths": f"{known_wallet}\n{unknown_wallet}"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    job_id = _job_id_from_redirect(resp)
    _wait_for_terminal(client, job_id)
    mock_run_scan.assert_called_once_with([str(known_wallet)])


@patch("web.app.credential_status_index")
@patch("web.app.run_credential_scan")
@patch("web.app.list_findings")
def test_check_credential_status_job_result_visible_via_normal_poll_not_secret(
    mock_list, mock_run_scan, mock_status_index, client, tmp_path
):
    """
    Unlike extract-key/auto-unlock, this job never touches private key
    material -- only public addresses and a key_type label -- so its
    result must NOT be hidden behind the once-only secret=True path; the
    normal /api/jobs/<id> poll must show it directly.
    """
    wallet = tmp_path / "wallet.dat"
    wallet.write_bytes(b"x")
    mock_list.return_value = [{"coin": "Bitcoin", "address": "1a", "source_path": str(wallet), "status": "new"}]
    mock_run_scan.return_value = {"report": "checked 1 wallet", "results": [{"wallet_path": str(wallet)}]}

    resp = client.post("/findings/check-credential-status", data={"wallet_paths": str(wallet)}, follow_redirects=False)
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_terminal(client, job_id)

    assert job["status"] == "done"
    assert job["result"] is not None
    assert job["result"]["report"] == "checked 1 wallet"
