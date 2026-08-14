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


@patch("web.app.list_vault_entries")
def test_vault_page_loads_and_never_shows_a_value(mock_list, client):
    mock_list.return_value = [{"name": "password-1", "state": "enabled", "description": "guess from 2015"}]

    resp = client.get("/vault")

    assert resp.status_code == 200
    assert b"password-1" in resp.data


@patch("web.app.add_vault_entry")
def test_vault_add_writes_value_to_temp_file_then_calls_add_vault_entry(mock_add, client):
    resp = client.post(
        "/vault/add",
        data={"name": "password-1", "value": "hunter2", "description": "guess from 2015"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    mock_add.assert_called_once()
    call_args = mock_add.call_args[0]
    assert call_args[0] == "password-1"
    assert "hunter2" not in call_args
    assert mock_add.call_args.kwargs.get("description") == "guess from 2015"


def test_vault_add_rejects_missing_name_or_value(client):
    resp = client.post("/vault/add", data={"name": "", "value": "hunter2"})
    assert resp.status_code == 400


@patch("web.app.revoke_vault_entry")
def test_vault_revoke_calls_revoke_vault_entry(mock_revoke, client):
    resp = client.post("/vault/revoke", data={"name": "password-1"}, follow_redirects=False)

    assert resp.status_code == 302
    mock_revoke.assert_called_once_with("password-1")


@patch("web.app.resolve_vault_entries_with_values")
@patch("web.app.run_unlock")
@patch("web.app.check_network_status")
def test_unlock_with_vault_entries_combines_candidates_and_annotates_match(
    mock_status, mock_run_unlock, mock_resolve, client, tmp_path
):
    mock_status.return_value = "OFFLINE"
    mock_resolve.return_value = [("password-1", "hunter2")]
    mock_run_unlock.return_value = SimpleNamespace(stdout="Password found: hunter2", stderr="", returncode=0)
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = client.post(
        "/item/unlock",
        data={"target_path": str(wallet_file), "candidates": "", "kind": "btcrecover", "vault_entries": ["password-1"]},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_terminal(client, job_id)
    assert job["status"] == "done"

    result_view = client.get(f"/item/unlock-result/{job_id}")
    assert result_view.status_code == 200
    assert b"password-1" in result_view.data


@patch("web.app.check_network_status")
def test_unlock_requires_candidates_or_vault_entries(mock_status, client, tmp_path):
    mock_status.return_value = "OFFLINE"
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = client.post("/item/unlock", data={"target_path": str(wallet_file), "candidates": "", "kind": "btcrecover"})

    assert resp.status_code == 400
