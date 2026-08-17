import time
from unittest.mock import MagicMock, patch

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _wait_for_job(client, job_id, timeout_iterations=100):
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


def test_lookup_form_loads(client):
    resp = client.get("/lookup")
    assert resp.status_code == 200
    assert b"Bitcoin" in resp.data  # from WALLET_SERVICES-populated <select>


def test_lookup_requires_coin_and_address(client):
    resp = client.post("/lookup", data={"coin": "", "address": ""})
    assert resp.status_code == 400
    assert b"Enter" in resp.data


@patch("web.app.record_finding")
@patch("web.app._check_balance_with_retries")
@patch("web.app.load_service")
def test_lookup_checks_and_records(mock_load_service, mock_check, mock_record, client):
    mock_service = MagicMock()
    mock_load_service.return_value = mock_service
    mock_check.return_value = 0.75

    resp = client.post("/lookup", data={"coin": "Bitcoin", "address": "1abc"}, follow_redirects=False)
    assert resp.status_code == 302
    job = _wait_for_job(client, _job_id_from_redirect(resp))

    assert job["status"] == "done"
    mock_load_service.assert_called_once_with("Bitcoin")
    mock_check.assert_called_once_with(mock_service, "1abc")
    mock_record.assert_called_once_with("Bitcoin", "1abc", 0.75, source_label="quick_lookup")
    assert "0.75" in job["result"]["report"]


@patch("web.app.record_finding")
@patch("web.app._check_balance_with_retries", return_value=None)
@patch("web.app.load_service")
def test_lookup_handles_inconclusive_balance(mock_load_service, mock_check, mock_record, client):
    mock_load_service.return_value = MagicMock()

    resp = client.post("/lookup", data={"coin": "Bitcoin", "address": "1abc"}, follow_redirects=False)
    job = _wait_for_job(client, _job_id_from_redirect(resp))

    assert job["status"] == "done"
    mock_record.assert_called_once_with("Bitcoin", "1abc", None, source_label="quick_lookup")


def test_index_page_links_to_lookup(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'href="/lookup"' in resp.data
