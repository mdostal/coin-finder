import time
from types import SimpleNamespace
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


@patch("web.app.list_vault_entries", return_value=[{"name": "password-1", "description": "", "state": "enabled"}])
@patch("web.app.list_findings", return_value=[{"coin": "Bitcoin", "address": "1abc", "source_path": "/w.dat", "status": "new"}])
@patch("web.app.check_network_status", return_value="OFFLINE")
def test_auto_unlock_form_shows_offline_status_and_known_wallets(mock_status, mock_findings, mock_vault, client, tmp_path):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")
    mock_findings.return_value[0]["source_path"] = str(wallet_file)

    resp = client.get("/auto-unlock")

    assert resp.status_code == 200
    assert b"OFFLINE" in resp.data
    assert str(wallet_file).encode() in resp.data


@patch("web.app.run_unlock")
@patch("web.app.check_network_status", return_value="ONLINE")
def test_post_auto_unlock_refused_when_online(mock_status, mock_run_unlock, client):
    resp = client.post("/auto-unlock", data={})
    assert resp.status_code == 409
    mock_run_unlock.assert_not_called()


@patch("web.app.list_vault_entries", return_value=[])
@patch("web.app.check_network_status", return_value="OFFLINE")
def test_post_auto_unlock_requires_at_least_one_vault_entry(mock_status, mock_vault, client):
    resp = client.post("/auto-unlock", data={})
    assert resp.status_code == 400
    assert b"vault" in resp.data.lower()


@patch("web.app.run_unlock")
@patch("web.app.resolve_vault_entries_with_values", return_value=[("password-1", "hunter2")])
@patch("web.app.list_vault_entries", return_value=[{"name": "password-1", "description": "", "state": "enabled"}])
@patch("web.app.list_findings")
@patch("web.app.check_network_status", return_value="OFFLINE")
def test_auto_unlock_tries_every_known_wallet_against_vault(mock_status, mock_findings, mock_vault, mock_resolve, mock_run_unlock, client, tmp_path):
    wallet_a = tmp_path / "a.dat"
    wallet_a.write_bytes(b"x")
    wallet_b = tmp_path / "b.dat"
    wallet_b.write_bytes(b"x")
    mock_findings.return_value = [
        {"coin": "Bitcoin", "address": "1a", "source_path": str(wallet_a), "status": "new"},
        {"coin": "Bitcoin", "address": "1b", "source_path": str(wallet_b), "status": "archived"},
    ]
    mock_run_unlock.return_value = SimpleNamespace(stdout="No password found.", stderr="", returncode=1)

    resp = client.post("/auto-unlock", data={}, follow_redirects=False)
    assert resp.status_code == 302
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_terminal(client, job_id)

    assert job["status"] == "done"
    assert mock_run_unlock.call_count == 2
    tried_paths = {c.args[0] for c in mock_run_unlock.call_args_list}
    assert tried_paths == {str(wallet_a), str(wallet_b)}
    # every call reuses the same shared candidates file
    candidate_paths = {c.args[1] for c in mock_run_unlock.call_args_list}
    assert len(candidate_paths) == 1


@patch("web.app.run_exodus_unlock")
@patch("web.app.run_unlock")
@patch("web.app.resolve_vault_entries_with_values", return_value=[("password-1", "hunter2")])
@patch("web.app.list_vault_entries", return_value=[{"name": "password-1", "description": "", "state": "enabled"}])
@patch("web.app.list_findings")
@patch("web.app.check_network_status", return_value="OFFLINE")
def test_auto_unlock_routes_seco_files_to_exodus_runner(mock_status, mock_findings, mock_vault, mock_resolve, mock_run_unlock, mock_run_exodus, client, tmp_path):
    seco_file = tmp_path / "seed.seco"
    seco_file.write_bytes(b"x")
    mock_findings.return_value = [{"coin": "Bitcoin", "address": "1a", "source_path": str(seco_file), "status": "new"}]
    mock_run_exodus.return_value = SimpleNamespace(stdout="No password found.", stderr="", returncode=1)

    resp = client.post("/auto-unlock", data={}, follow_redirects=False)
    job_id = _job_id_from_redirect(resp)
    _wait_for_terminal(client, job_id)

    mock_run_exodus.assert_called_once()
    mock_run_unlock.assert_not_called()


@patch("web.app.run_unlock")
@patch("web.app.resolve_vault_entries_with_values", return_value=[("password-1", "hunter2!!")])
@patch("web.app.list_vault_entries", return_value=[{"name": "password-1", "description": "", "state": "enabled"}])
@patch("web.app.list_findings")
@patch("web.app.check_network_status", return_value="OFFLINE")
def test_auto_unlock_result_delivered_once_then_gone(mock_status, mock_findings, mock_vault, mock_resolve, mock_run_unlock, client, tmp_path):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")
    mock_findings.return_value = [{"coin": "Bitcoin", "address": "1a", "source_path": str(wallet_file), "status": "new"}]
    mock_run_unlock.return_value = SimpleNamespace(stdout="Password found: hunter2!!", stderr="", returncode=0)

    resp = client.post("/auto-unlock", data={}, follow_redirects=False)
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_terminal(client, job_id)
    assert job["status"] == "done"
    assert "hunter2" not in str(job)  # plain status/poll path never carries the secret

    first_view = client.get(f"/auto-unlock/result/{job_id}")
    assert first_view.status_code == 200
    assert b"password-1" in first_view.data  # matched label shown, not the raw value

    second_view = client.get(f"/auto-unlock/result/{job_id}")
    assert second_view.status_code == 404


def test_auto_unlock_result_unknown_job_is_404(client):
    resp = client.get("/auto-unlock/result/does-not-exist")
    assert resp.status_code == 404
