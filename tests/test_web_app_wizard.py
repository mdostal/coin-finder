from unittest.mock import patch

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_wizard_start_page_loads(client):
    resp = client.get("/wizard")
    assert resp.status_code == 200


def test_wizard_choose_local_hands_off_to_scan_form(client):
    resp = client.post("/wizard/choose", data={"target_type": "local"}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"


def test_wizard_choose_volume_hands_off_to_targets_page(client):
    resp = client.post("/wizard/choose", data={"target_type": "volume"}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/targets"


def test_wizard_choose_gdrive_hands_off_to_cloud_explainer(client):
    resp = client.post("/wizard/choose", data={"target_type": "gdrive"}, follow_redirects=False)
    assert resp.status_code == 302
    assert "/wizard/cloud" in resp.headers["Location"]
    assert "kind=gdrive" in resp.headers["Location"]


@patch("web.app.list_remotes")
@patch("web.app._is_rclone_installed")
def test_wizard_cloud_page_surfaces_install_step_when_rclone_not_set_up(mock_installed, mock_remotes, client):
    mock_installed.return_value = False
    mock_remotes.return_value = []

    resp = client.get("/wizard/cloud?kind=gdrive")

    assert resp.status_code == 200
    assert b"install_rclone.sh" in resp.data


@patch("web.app.list_remotes")
@patch("web.app._is_rclone_installed")
def test_wizard_cloud_page_links_to_mounts_when_remotes_exist(mock_installed, mock_remotes, client):
    mock_installed.return_value = True
    mock_remotes.return_value = ["gdrive"]

    resp = client.get("/wizard/cloud?kind=gdrive")

    assert resp.status_code == 200
    assert b"/mounts" in resp.data


def test_wizard_never_claims_mount_success_itself(client):
    """The wizard's cloud page must never render a hardcoded success claim --
    only /mounts (which does the real is_mounted() check) may."""
    resp = client.get("/wizard/cloud?kind=gdrive")
    assert b"Drive mounted!" not in resp.data
    assert b"Successfully mounted" not in resp.data
