from unittest.mock import patch

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@patch("web.app.remote_status")
@patch("web.app.list_mounts")
@patch("web.app.list_remotes")
def test_mounts_page_loads(mock_remotes, mock_mounts, mock_status, client):
    mock_remotes.return_value = ["gdrive"]
    mock_mounts.return_value = []
    mock_status.return_value = "connected"

    resp = client.get("/mounts")

    assert resp.status_code == 200


@patch("web.app.remote_status")
@patch("web.app.list_mounts")
@patch("web.app.list_remotes")
def test_mounts_page_shows_status_pill_per_remote(mock_remotes, mock_mounts, mock_status, client):
    mock_remotes.return_value = ["gdrive"]
    mock_mounts.return_value = []
    mock_status.return_value = "incomplete"

    resp = client.get("/mounts")

    assert resp.status_code == 200
    assert b"incomplete" in resp.data.lower()


@patch("web.app.remove_remote")
def test_mounts_remove_calls_remove_remote(mock_remove, client):
    resp = client.post("/mounts/remove", data={"remote_name": "gdrive"}, follow_redirects=False)

    assert resp.status_code == 302
    mock_remove.assert_called_once_with("gdrive")


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


@patch("web.app.install_rclone")
def test_mounts_install_rclone_starts_a_job(mock_install, client):
    mock_install.return_value = {"ok": True, "report": "installed rclone and macfuse"}

    resp = client.post("/mounts/install-rclone", follow_redirects=False)

    assert resp.status_code == 302
    assert "/item-result/" in resp.headers["Location"]


@patch("web.app.list_mounts")
@patch("web.app.list_remotes")
@patch("web.app.is_rclone_installed")
def test_mounts_page_never_tells_you_to_open_a_terminal(mock_installed, mock_remotes, mock_mounts, client):
    """Direct regression test for the reported bug: this page must not send
    the user to a terminal for `rclone config` -- it must link to the
    in-app wizard instead, both when rclone isn't installed yet and when
    it's installed but no remote is configured."""
    mock_installed.return_value = False
    mock_remotes.return_value = []
    mock_mounts.return_value = []

    resp = client.get("/mounts")

    assert resp.status_code == 200
    assert b"rclone config" not in resp.data
    assert b"/wizard/cloud" in resp.data


@patch("web.app.list_mounts")
@patch("web.app.list_remotes")
@patch("web.app.is_rclone_installed")
def test_mounts_page_links_to_wizard_when_no_remotes_configured(mock_installed, mock_remotes, mock_mounts, client):
    mock_installed.return_value = True
    mock_remotes.return_value = []
    mock_mounts.return_value = []

    resp = client.get("/mounts")

    assert resp.status_code == 200
    assert b"No rclone remotes configured yet" in resp.data
    assert b"/wizard/cloud" in resp.data
