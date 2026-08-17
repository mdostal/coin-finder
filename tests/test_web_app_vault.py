import re
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


@patch("web.app.edit_vault_entry")
def test_vault_edit_calls_edit_vault_entry(mock_edit, client):
    resp = client.post("/vault/edit", data={"name": "password-1", "description": "updated"}, follow_redirects=False)

    assert resp.status_code == 302
    mock_edit.assert_called_once_with("password-1", "updated")


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


@patch("web.app.resolve_vault_entries_with_values")
def test_vault_reveal_shows_the_real_value_once(mock_resolve, client):
    mock_resolve.return_value = [("password-1", "hunter2!!")]

    resp = client.post("/vault/reveal", data={"name": "password-1"})

    assert resp.status_code == 200
    assert b"hunter2!!" in resp.data
    mock_resolve.assert_called_once_with(["password-1"])


def test_vault_reveal_rejects_empty_name(client):
    resp = client.post("/vault/reveal", data={"name": ""})
    assert resp.status_code == 400


@patch("web.app.resolve_vault_entries_with_values", side_effect=RuntimeError("Could not resolve vault entry 'nope'"))
def test_vault_reveal_surfaces_resolve_failure_as_an_error(mock_resolve, client):
    resp = client.post("/vault/reveal", data={"name": "nope"})
    assert resp.status_code == 400


@patch("web.app.resolve_vault_entries_with_values")
def test_vault_reveal_never_creates_a_job(mock_resolve, client):
    """Synchronous, not backgrounded -- a reveal must never show up in /jobs' generic listing."""
    mock_resolve.return_value = [("password-1", "hunter2!!")]

    client.post("/vault/reveal", data={"name": "password-1"})

    jobs_resp = client.get("/jobs")
    assert b"hunter2!!" not in jobs_resp.data


@patch("web.app.resolve_vault_entries_with_values")
def test_vault_reveal_masks_value_by_default_with_eye_toggle(mock_resolve, client):
    """
    ccu-01: the vault reveal page must not paint the real secret as its
    default visible text -- masked placeholder + eye-toggle, real value
    still present in the initial HTML (data attribute) so no second
    request is needed to reveal it.
    """
    mock_resolve.return_value = [("password-1", "hunter2!!")]

    resp = client.post("/vault/reveal", data={"name": "password-1"})

    assert resp.status_code == 200
    html = resp.data.decode()

    assert 'data-secret="hunter2!!"' in html

    match = re.search(r'<code class="secret-mask"[^>]*>([^<]*)</code>', html)
    assert match is not None, "expected a masked secret-mask element on the reveal page"
    visible_text = match.group(1)
    assert "hunter2!!" not in visible_text
    assert visible_text.strip() != ""

    assert 'class="secret-reveal-btn' in html


@patch("web.app.list_auto_unlock_history")
def test_auto_unlock_history_page_shows_past_runs(mock_list, client):
    mock_list.return_value = [
        {
            "run_id": "abc",
            "run_at": 1700000000.0,
            "wallets": [
                {"wallet_path": "/wallets/a.dat", "vault_label": "password-1", "matched": True},
                {"wallet_path": "/wallets/b.dat", "vault_label": None, "matched": False},
            ],
        }
    ]

    resp = client.get("/auto-unlock/history")

    assert resp.status_code == 200
    assert b"/wallets/a.dat" in resp.data
    assert b"password-1" in resp.data
    assert b"/wallets/b.dat" in resp.data
    assert b"no match" in resp.data.lower()


@patch("web.app.list_auto_unlock_history", return_value=[])
def test_auto_unlock_history_page_shows_empty_state(mock_list, client):
    resp = client.get("/auto-unlock/history")
    assert resp.status_code == 200
    assert b"No auto-unlock runs recorded yet" in resp.data


@patch("web.app.clear_auto_unlock_history")
def test_auto_unlock_history_clear_calls_clear_and_redirects(mock_clear, client):
    resp = client.post("/auto-unlock/history/clear", follow_redirects=False)

    assert resp.status_code == 302
    mock_clear.assert_called_once()


@patch("web.app.record_auto_unlock_run")
@patch("web.app.run_unlock")
@patch("web.app.resolve_vault_entries_with_values", return_value=[("password-1", "hunter2!!")])
@patch("web.app.list_vault_entries", return_value=[{"name": "password-1", "description": "", "state": "enabled"}])
@patch("web.app.list_findings")
@patch("web.app.check_network_status", return_value="OFFLINE")
def test_auto_unlock_job_records_history_after_completion(
    mock_status, mock_findings, mock_vault, mock_resolve, mock_run_unlock, mock_record_history, client, tmp_path
):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")
    mock_findings.return_value = [{"coin": "Bitcoin", "address": "1a", "source_path": str(wallet_file), "status": "new"}]
    mock_run_unlock.return_value = SimpleNamespace(stdout="Password found: hunter2!!", stderr="", returncode=0)

    resp = client.post("/auto-unlock", data={}, follow_redirects=False)
    job_id = _job_id_from_redirect(resp)
    _wait_for_terminal(client, job_id)

    mock_record_history.assert_called_once()
    results_arg = mock_record_history.call_args[0][0]
    assert results_arg[str(wallet_file)]["vault_label"] == "password-1"
