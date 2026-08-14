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


@patch("web.app.check_network_status")
def test_extract_key_form_shows_network_status(mock_status, client):
    mock_status.return_value = "OFFLINE"
    resp = client.get("/item/extract-key")
    assert resp.status_code == 200
    assert b"OFFLINE" in resp.data


@patch("web.app.extract_wif_for_address")
@patch("web.app.check_network_status")
def test_extract_key_refused_when_online(mock_status, mock_extract, client, tmp_path):
    mock_status.return_value = "ONLINE"
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = client.post("/item/extract-key", data={"wallet_path": str(wallet_file), "address": "1abc"})

    assert resp.status_code == 409
    mock_extract.assert_not_called()


@patch("web.app.extract_wif_for_address")
@patch("web.app.check_network_status")
def test_extract_key_with_allow_online_checkbox_proceeds_while_online(mock_status, mock_extract, client, tmp_path):
    mock_status.return_value = "ONLINE"
    mock_extract.return_value = "5JsomeRealLookingWIFStringHere1234567890abcd"
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = client.post(
        "/item/extract-key",
        data={"wallet_path": str(wallet_file), "address": "1abc", "allow_online": "1"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    mock_extract.assert_called_once_with(str(wallet_file), "1abc", allow_online=True)


@patch("web.app.extract_wif_for_address")
@patch("web.app.check_network_status")
def test_extract_key_result_delivered_once_then_gone(mock_status, mock_extract, client, tmp_path):
    mock_status.return_value = "OFFLINE"
    mock_extract.return_value = "5JsomeRealLookingWIFStringHere1234567890abcd"
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = client.post(
        "/item/extract-key",
        data={"wallet_path": str(wallet_file), "address": "1abc"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_terminal(client, job_id)
    assert job["status"] == "done"

    # The plain status/poll path must never carry the extracted key.
    assert "5Jsome" not in str(job)

    first_view = client.get(f"/item/extract-key-result/{job_id}")
    assert first_view.status_code == 200
    assert b"5Jsome" in first_view.data

    second_view = client.get(f"/item/extract-key-result/{job_id}")
    assert second_view.status_code == 404


@patch("web.app.extract_wif_for_address")
@patch("web.app.check_network_status")
def test_extract_key_defaults_allow_online_false_when_checkbox_unchecked(mock_status, mock_extract, client, tmp_path):
    mock_status.return_value = "OFFLINE"
    mock_extract.return_value = "5Jwif"
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")

    resp = client.post("/item/extract-key", data={"wallet_path": str(wallet_file), "address": "1abc"}, follow_redirects=False)
    job_id = _job_id_from_redirect(resp)
    _wait_for_terminal(client, job_id)

    mock_extract.assert_called_once_with(str(wallet_file), "1abc", allow_online=False)


def test_extract_key_rejects_missing_wallet_file(client, tmp_path):
    with patch("web.app.check_network_status", return_value="OFFLINE"):
        resp = client.post("/item/extract-key", data={"wallet_path": str(tmp_path / "nope.dat"), "address": "1abc"})
    assert resp.status_code == 400
