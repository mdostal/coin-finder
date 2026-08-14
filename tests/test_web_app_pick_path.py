from unittest.mock import patch

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@patch("web.app.pick_path")
def test_pick_path_returns_chosen_path(mock_pick, client):
    mock_pick.return_value = "/Users/x/wallet.dat"

    resp = client.post("/api/pick-path", data={"mode": "file"})

    assert resp.status_code == 200
    assert resp.get_json() == {"path": "/Users/x/wallet.dat"}
    mock_pick.assert_called_once_with(mode="file")


@patch("web.app.pick_path")
def test_pick_path_returns_null_on_cancel(mock_pick, client):
    mock_pick.return_value = None

    resp = client.post("/api/pick-path", data={"mode": "directory"})

    assert resp.status_code == 200
    assert resp.get_json() == {"path": None}


@patch("web.app.pick_path")
def test_pick_path_reports_unsupported_platform_as_400(mock_pick, client):
    mock_pick.side_effect = RuntimeError("Native file picker isn't supported on this platform (Windows).")

    resp = client.post("/api/pick-path", data={"mode": "file"})

    assert resp.status_code == 400
    assert "error" in resp.get_json()


@patch("web.app.pick_path")
def test_pick_path_defaults_to_file_mode(mock_pick, client):
    mock_pick.return_value = None

    client.post("/api/pick-path", data={})

    mock_pick.assert_called_once_with(mode="file")
