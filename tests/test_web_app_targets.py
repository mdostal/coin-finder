from unittest.mock import patch

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@patch("web.app.list_mounted_volumes")
@patch("web.app.list_targets")
def test_targets_page_loads(mock_list_targets, mock_list_volumes, client):
    mock_list_targets.return_value = [{"label": "A", "path": "/a", "kind": "local", "added_at": 0}]
    mock_list_volumes.return_value = [{"name": "OldDrive", "path": "/Volumes/OldDrive", "is_bound": False}]

    resp = client.get("/targets")

    assert resp.status_code == 200


@patch("web.app.add_target")
def test_targets_add_calls_add_target(mock_add, client, tmp_path):
    resp = client.post("/targets/add", data={"label": "Old Drive", "path": str(tmp_path), "kind": "volume"}, follow_redirects=False)

    assert resp.status_code == 302
    mock_add.assert_called_once_with("Old Drive", str(tmp_path), "volume")


@patch("web.app.remove_target")
def test_targets_remove_calls_remove_target(mock_remove, client):
    resp = client.post("/targets/remove", data={"label": "Old Drive"}, follow_redirects=False)

    assert resp.status_code == 302
    mock_remove.assert_called_once_with("Old Drive")


def test_targets_add_rejects_missing_path(client):
    resp = client.post("/targets/add", data={"label": "X", "path": "", "kind": "local"})
    assert resp.status_code == 400
