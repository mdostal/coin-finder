from unittest.mock import patch

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@patch("web.app.check_for_update")
def test_update_page_shows_update_available(mock_check, client):
    mock_check.return_value = {"current": "0.24.0", "latest": "0.25.0", "update_available": True}

    resp = client.get("/update")

    assert resp.status_code == 200
    assert b"0.24.0" in resp.data
    assert b"0.25.0" in resp.data


@patch("web.app.check_for_update")
def test_update_page_shows_up_to_date(mock_check, client):
    mock_check.return_value = {"current": "0.24.0", "latest": "0.24.0", "update_available": False}

    resp = client.get("/update")

    assert resp.status_code == 200
    assert b"0.24.0" in resp.data


@patch("web.app.perform_update")
def test_update_run_success_shows_restart_message(mock_perform, client):
    mock_perform.return_value = {"ok": True, "output": "Fast-forward"}

    resp = client.post("/update/run")

    assert resp.status_code == 200
    assert b"restart" in resp.data.lower()


@patch("web.app.perform_update")
def test_update_run_failure_shows_error(mock_perform, client):
    mock_perform.return_value = {"ok": False, "output": "fatal: Not possible to fast-forward, aborting."}

    resp = client.post("/update/run")

    assert resp.status_code == 200
    assert b"fast-forward" in resp.data
