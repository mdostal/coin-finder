from unittest.mock import patch

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@patch("web.app.list_mounts")
@patch("web.app.list_remotes")
def test_mounts_page_loads(mock_remotes, mock_mounts, client):
    mock_remotes.return_value = ["gdrive"]
    mock_mounts.return_value = []

    resp = client.get("/mounts")

    assert resp.status_code == 200


@patch("web.app.mount")
def test_mounts_mount_calls_mount(mock_mount, client, tmp_path):
    resp = client.post("/mounts/mount", data={"remote_name": "gdrive", "mount_point": str(tmp_path / "mnt")}, follow_redirects=False)

    assert resp.status_code == 302
    mock_mount.assert_called_once_with("gdrive", str(tmp_path / "mnt"))


@patch("web.app.unmount")
def test_mounts_unmount_calls_unmount(mock_unmount, client):
    resp = client.post("/mounts/unmount", data={"remote_name": "gdrive"}, follow_redirects=False)

    assert resp.status_code == 302
    mock_unmount.assert_called_once_with("gdrive")


@patch("web.app.add_target")
@patch("web.app.is_mounted")
def test_mounts_bind_adds_to_bound_targets_when_actually_mounted(mock_is_mounted, mock_add_target, client, tmp_path):
    mock_is_mounted.return_value = True

    resp = client.post(
        "/mounts/bind",
        data={"remote_name": "gdrive", "mount_point": str(tmp_path / "mnt"), "kind": "gdrive-mount"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    mock_add_target.assert_called_once_with("gdrive", str(tmp_path / "mnt"), "gdrive-mount")


@patch("web.app.add_target")
@patch("web.app.is_mounted")
def test_mounts_bind_refuses_when_not_actually_mounted(mock_is_mounted, mock_add_target, client, tmp_path):
    mock_is_mounted.return_value = False

    resp = client.post(
        "/mounts/bind",
        data={"remote_name": "gdrive", "mount_point": str(tmp_path / "mnt"), "kind": "gdrive-mount"},
        follow_redirects=False,
    )

    assert resp.status_code == 409
    mock_add_target.assert_not_called()
