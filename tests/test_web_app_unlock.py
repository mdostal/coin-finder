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
    """Polls /api/jobs/<job_id> (the non-consuming status path) until terminal."""
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


@patch("web.app.check_network_status")
def test_unlock_form_shows_current_network_status(mock_status, client):
    mock_status.return_value = "OFFLINE"
    resp = client.get("/item/unlock")
    assert resp.status_code == 200
    assert b"OFFLINE" in resp.data


@patch("web.app.run_unlock")
@patch("web.app.check_network_status")
def test_post_unlock_refused_when_online(mock_status, mock_run_unlock, client, tmp_path):
    mock_status.return_value = "ONLINE"
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = client.post(
        "/item/unlock",
        data={"target_path": str(wallet_file), "candidates": "hunter2\n", "kind": "btcrecover"},
    )

    assert resp.status_code == 409
    mock_run_unlock.assert_not_called()


@patch("web.app.run_unlock")
@patch("web.app.check_network_status")
def test_post_unlock_refused_when_status_unknown(mock_status, mock_run_unlock, client, tmp_path):
    mock_status.return_value = "UNKNOWN"
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = client.post(
        "/item/unlock",
        data={"target_path": str(wallet_file), "candidates": "hunter2\n", "kind": "btcrecover"},
    )

    assert resp.status_code == 409
    mock_run_unlock.assert_not_called()


@patch("web.app.run_unlock")
@patch("web.app.check_network_status")
def test_post_unlock_writes_candidates_to_temp_file_not_raw_arg(mock_status, mock_run_unlock, client, tmp_path):
    mock_status.return_value = "OFFLINE"
    mock_run_unlock.return_value = SimpleNamespace(stdout="No password found.", stderr="", returncode=1)
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = client.post(
        "/item/unlock",
        data={"target_path": str(wallet_file), "candidates": "hunter2\ncorrecthorse\n", "kind": "btcrecover"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_terminal(client, job_id)
    assert job["status"] == "done"

    call_args = mock_run_unlock.call_args[0]
    candidates_path = call_args[1]
    assert candidates_path != "hunter2\ncorrecthorse\n"
    assert "hunter2" not in call_args
    # temp file is cleaned up after the job completes
    import os

    assert not os.path.exists(candidates_path)


@patch("web.app.run_exodus_unlock")
@patch("web.app.check_network_status")
def test_post_unlock_exodus_kind_calls_exodus_unlock(mock_status, mock_run_exodus, client, tmp_path):
    mock_status.return_value = "OFFLINE"
    mock_run_exodus.return_value = SimpleNamespace(stdout="No password found.", stderr="", returncode=1)
    seco_file = tmp_path / "seed.seco"
    seco_file.write_bytes(b"x")

    resp = client.post(
        "/item/unlock",
        data={"target_path": str(seco_file), "candidates": "hunter2\n", "kind": "exodus"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_terminal(client, job_id)
    assert job["status"] == "done"
    mock_run_exodus.assert_called_once()


@patch("web.app.run_unlock")
@patch("web.app.check_network_status")
def test_unlock_result_delivered_once_then_gone(mock_status, mock_run_unlock, client, tmp_path):
    mock_status.return_value = "OFFLINE"
    mock_run_unlock.return_value = SimpleNamespace(stdout="Password found: hunter2!!", stderr="", returncode=0)
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = client.post(
        "/item/unlock",
        data={"target_path": str(wallet_file), "candidates": "hunter2!!\n", "kind": "btcrecover"},
        follow_redirects=False,
    )
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_terminal(client, job_id)
    assert job["status"] == "done"

    # The plain status/poll path must never carry the secret-bearing result.
    assert "hunter2" not in str(job)

    first_view = client.get(f"/item/unlock-result/{job_id}")
    assert first_view.status_code == 200
    assert b"hunter2" in first_view.data

    second_view = client.get(f"/item/unlock-result/{job_id}")
    assert second_view.status_code == 404


def test_unlock_result_unknown_job_is_404(client):
    resp = client.get("/item/unlock-result/does-not-exist")
    assert resp.status_code == 404


def test_post_unlock_rejects_missing_target_file(client, tmp_path):
    with patch("web.app.check_network_status", return_value="OFFLINE"):
        resp = client.post(
            "/item/unlock",
            data={"target_path": str(tmp_path / "nope.dat"), "candidates": "hunter2\n", "kind": "btcrecover"},
        )
    assert resp.status_code == 400
