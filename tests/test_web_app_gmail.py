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


@patch("web.app.is_gmail_bound", return_value=False)
def test_gmail_form_shows_connect_form_when_not_bound(mock_bound, client):
    resp = client.get("/gmail")
    assert resp.status_code == 200
    assert b'name="client_id"' in resp.data
    assert b'name="queries"' not in resp.data


@patch("web.app.is_gmail_bound", return_value=True)
def test_gmail_form_shows_search_form_when_bound(mock_bound, client):
    resp = client.get("/gmail")
    assert resp.status_code == 200
    assert b'name="queries"' in resp.data
    assert b'name="client_id"' not in resp.data


def test_gmail_connect_requires_both_fields(client):
    resp = client.post("/gmail/connect", data={"client_id": "", "client_secret": ""})
    assert resp.status_code == 400
    assert b"client ID and client secret" in resp.data


@patch("web.app.bind_gmail_account")
def test_gmail_connect_runs_bind_as_a_background_job(mock_bind, client):
    mock_bind.return_value = {"ok": True, "report": "Connected -- Gmail is ready to search."}

    resp = client.post("/gmail/connect", data={"client_id": "id.apps.googleusercontent.com", "client_secret": "shh"}, follow_redirects=False)
    assert resp.status_code == 302
    job = _wait_for_terminal(client, _job_id_from_redirect(resp))

    assert job["status"] == "done"
    mock_bind.assert_called_once()
    assert mock_bind.call_args[0][0] == "id.apps.googleusercontent.com"
    assert mock_bind.call_args[0][1] == "shh"


@patch("web.app.unbind_gmail_account")
def test_gmail_disconnect_calls_unbind_and_redirects(mock_unbind, client):
    resp = client.post("/gmail/disconnect", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/gmail")
    mock_unbind.assert_called_once()


@patch("web.app.is_gmail_bound", return_value=False)
def test_gmail_search_refused_when_not_bound(mock_bound, client):
    resp = client.post("/gmail/search", data={})
    assert resp.status_code == 409


@patch("web.app.scan_gmail_for_wallet_clues")
@patch("web.app.is_gmail_bound", return_value=True)
def test_gmail_search_runs_scan_as_a_background_job(mock_bound, mock_scan, client, tmp_path):
    mock_scan.return_value = [
        {"id": "1", "from": "coinbase.com", "subject": "Withdrawal", "date": "today", "addresses": {"Bitcoin": ["1abc"]}, "attachments_saved": []}
    ]

    resp = client.post(
        "/gmail/search",
        data={"output_dir": str(tmp_path), "queries": "from:coinbase.com\nwallet.dat"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    job = _wait_for_terminal(client, _job_id_from_redirect(resp))

    assert job["status"] == "done"
    mock_scan.assert_called_once()
    args, kwargs = mock_scan.call_args
    assert args[0] == str(tmp_path)
    assert kwargs["queries"] == ["from:coinbase.com", "wallet.dat"]


@patch("web.app.scan_gmail_for_wallet_clues")
@patch("web.app.is_gmail_bound", return_value=True)
def test_gmail_search_result_page_shows_addresses_not_raw_body(mock_bound, mock_scan, client, tmp_path):
    mock_scan.return_value = [
        {"id": "1", "from": "coinbase.com", "subject": "Withdrawal", "date": "today", "addresses": {"Bitcoin": ["1abc"]}, "attachments_saved": ["/tmp/1_wallet.dat"]}
    ]

    resp = client.post("/gmail/search", data={"output_dir": str(tmp_path), "queries": ""}, follow_redirects=False)
    job_id = _job_id_from_redirect(resp)
    _wait_for_terminal(client, job_id)

    view = client.get(f"/item-result/{job_id}")
    assert view.status_code == 200
    assert b"1abc" in view.data
    assert b"coinbase.com" in view.data
    assert b"/tmp/1_wallet.dat" in view.data
