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


@patch("web.app.remote_status", return_value="connected")
@patch("web.app.list_mounts")
@patch("web.app.list_remotes")
def test_mounts_page_shows_log_tail_for_a_failed_mount(mock_remotes, mock_mounts, mock_status, client, tmp_path):
    """
    Regression test for a real bug hit live: a failed mount showed a bare
    "ERROR" pill with zero diagnostic information -- rclone's own real
    error message (e.g. "rclone mount is not supported on MacOS...") was
    being discarded (stderr=DEVNULL). Now captured to a log file and
    surfaced here.
    """
    log_path = tmp_path / "gdrive.log"
    log_path.write_text("CRITICAL: Fatal error: failed to mount FUSE fs: some real reason\n")
    mock_remotes.return_value = ["gdrive"]
    mock_mounts.return_value = [{"remote_name": "gdrive", "mount_point": "/mnt", "started_at": 0, "is_mounted": False, "log_path": str(log_path)}]

    resp = client.get("/mounts")

    assert resp.status_code == 200
    assert b"failed to mount FUSE fs" in resp.data


@patch("web.app.remote_status", return_value="connected")
@patch("web.app.list_mounts")
@patch("web.app.list_remotes")
def test_mounts_page_no_log_tail_for_a_healthy_mount(mock_remotes, mock_mounts, mock_status, client, tmp_path):
    log_path = tmp_path / "gdrive.log"
    log_path.write_text("this is noise that should never be shown for a healthy mount\n")
    mock_remotes.return_value = ["gdrive"]
    mock_mounts.return_value = [{"remote_name": "gdrive", "mount_point": "/mnt", "started_at": 0, "is_mounted": True, "log_path": str(log_path)}]

    resp = client.get("/mounts")

    assert resp.status_code == 200
    assert b"this is noise" not in resp.data


@patch("web.app.start_job")
@patch("web.app.create_job")
def test_mounts_update_credentials_starts_a_background_job(mock_create_job, mock_start_job, client):
    """
    Mirrors test_wizard_cloud_connect_starts_a_background_job's pattern --
    the underlying update_remote_credentials() call blocks on a real
    browser-based OAuth handshake, same as create_remote(), so this route
    must never run it inline on the request thread.
    """
    mock_create_job.return_value = "job-456"

    resp = client.post(
        "/mounts/update-credentials",
        data={"remote_name": "gdrive", "client_id": "123456-abc.apps.googleusercontent.com", "client_secret": "shh"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/item-result/job-456"
    mock_create_job.assert_called_once_with(kind="update-remote-credentials", label="gdrive")
    mock_start_job.assert_called_once()
    job_args = mock_start_job.call_args[0]
    assert job_args[0] == "job-456"
    # the actual work function is backgrounded with the submitted remote/credentials, not run inline
    assert job_args[2:] == ("job-456", "gdrive", "123456-abc.apps.googleusercontent.com", "shh")


@patch("web.app.remote_status")
@patch("web.app.list_mounts")
@patch("web.app.list_remotes")
def test_mounts_update_credentials_requires_a_remote_name(mock_remotes, mock_mounts, mock_status, client):
    mock_remotes.return_value = ["gdrive"]
    mock_mounts.return_value = []
    mock_status.return_value = "connected"

    resp = client.post(
        "/mounts/update-credentials",
        data={"client_id": "123456-abc.apps.googleusercontent.com", "client_secret": "shh"},
    )

    assert resp.status_code == 400
    assert b"Missing remote name" in resp.data


# --- POST /mounts/test (gmc-02) -----------------------------------------


@patch("web.app.list_jobs")
@patch("web.app.start_job")
@patch("web.app.create_job")
def test_mounts_test_starts_a_background_job(mock_create_job, mock_start_job, mock_list_jobs, client):
    """
    A real mount+read cycle can take up to test_mount()'s own timeout --
    same as mounts_update_credentials(), this must never run inline on
    the request thread.
    """
    mock_list_jobs.return_value = []
    mock_create_job.return_value = "job-789"

    resp = client.post("/mounts/test", data={"remote_name": "gdrive"}, follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/item-result/job-789"
    mock_create_job.assert_called_once_with(kind="test-mount", label="gdrive")
    mock_start_job.assert_called_once()
    job_args = mock_start_job.call_args[0]
    assert job_args[0] == "job-789"
    assert job_args[2:] == ("gdrive",)


@patch("web.app.remote_status")
@patch("web.app.list_mounts")
@patch("web.app.list_remotes")
def test_mounts_test_requires_a_remote_name(mock_remotes, mock_mounts, mock_status, client):
    mock_remotes.return_value = ["gdrive"]
    mock_mounts.return_value = []
    mock_status.return_value = "connected"

    resp = client.post("/mounts/test", data={})

    assert resp.status_code == 400
    assert b"Missing remote name" in resp.data


@patch("web.app.remote_status")
@patch("web.app.list_mounts")
@patch("web.app.list_remotes")
@patch("web.app.create_job")
@patch("web.app.list_jobs")
def test_mounts_test_refuses_a_second_concurrent_test_for_the_same_remote(
    mock_list_jobs, mock_create_job, mock_remotes, mock_mounts, mock_status, client
):
    """
    Mirrors mounts_bind()'s existing 409 refusal on an unhealthy mount --
    a test-mount could itself trip the same rate limiting it exists to
    detect if two ran concurrently against the same remote.
    """
    mock_list_jobs.return_value = [{"job_id": "job-1", "kind": "test-mount", "label": "gdrive", "status": "running"}]
    mock_remotes.return_value = ["gdrive"]
    mock_mounts.return_value = []
    mock_status.return_value = "connected"

    resp = client.post("/mounts/test", data={"remote_name": "gdrive"}, follow_redirects=False)

    assert resp.status_code == 409
    mock_create_job.assert_not_called()


@patch("web.app.remote_status")
@patch("web.app.list_mounts")
@patch("web.app.list_remotes")
@patch("web.app.start_job")
@patch("web.app.create_job")
@patch("web.app.list_jobs")
def test_mounts_test_allows_a_test_for_a_different_remote_while_one_is_running(
    mock_list_jobs, mock_create_job, mock_start_job, mock_remotes, mock_mounts, mock_status, client
):
    mock_list_jobs.return_value = [{"job_id": "job-1", "kind": "test-mount", "label": "gdrive", "status": "running"}]
    mock_create_job.return_value = "job-2"
    mock_remotes.return_value = ["gdrive", "gcs-bucket"]
    mock_mounts.return_value = []
    mock_status.return_value = "connected"

    resp = client.post("/mounts/test", data={"remote_name": "gcs-bucket"}, follow_redirects=False)

    assert resp.status_code == 302
    mock_create_job.assert_called_once_with(kind="test-mount", label="gcs-bucket")


@patch("web.app.remote_status")
@patch("web.app.list_mounts")
@patch("web.app.list_remotes")
@patch("web.app.start_job")
@patch("web.app.create_job")
@patch("web.app.list_jobs")
def test_mounts_test_allows_a_new_test_once_the_prior_one_finished(
    mock_list_jobs, mock_create_job, mock_start_job, mock_remotes, mock_mounts, mock_status, client
):
    mock_list_jobs.return_value = [{"job_id": "job-1", "kind": "test-mount", "label": "gdrive", "status": "done"}]
    mock_create_job.return_value = "job-2"
    mock_remotes.return_value = ["gdrive"]
    mock_mounts.return_value = []
    mock_status.return_value = "connected"

    resp = client.post("/mounts/test", data={"remote_name": "gdrive"}, follow_redirects=False)

    assert resp.status_code == 302
    mock_create_job.assert_called_once_with(kind="test-mount", label="gdrive")


# --- POST /mounts/settings (gmc-03) --------------------------------------


@patch("web.app.save_mount_settings")
def test_mounts_settings_saves_and_redirects(mock_save, client):
    """
    A fast, local JSON write -- unlike mounts_update_credentials()/
    mounts_test(), this must run synchronously (no create_job()/
    start_job() backgrounding) since there's no OAuth handshake or bounded
    mount+read cycle to keep off the request thread.
    """
    resp = client.post("/mounts/settings", data={"remote_name": "gdrive", "checkers": "40", "tpslimit": "20"}, follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/mounts"
    mock_save.assert_called_once_with("gdrive", "40", "20")


@patch("web.app.remote_status")
@patch("web.app.list_mounts")
@patch("web.app.list_remotes")
def test_mounts_settings_requires_a_remote_name(mock_remotes, mock_mounts, mock_status, client):
    mock_remotes.return_value = ["gdrive"]
    mock_mounts.return_value = []
    mock_status.return_value = "connected"

    resp = client.post("/mounts/settings", data={"checkers": "40", "tpslimit": "20"})

    assert resp.status_code == 400
    assert b"Missing remote name" in resp.data


@patch("web.app.remote_status")
@patch("web.app.list_mounts")
@patch("web.app.list_remotes")
@patch("web.app.save_mount_settings")
def test_mounts_settings_rejects_invalid_values_with_a_400_and_never_touches_rclone(mock_save, mock_remotes, mock_mounts, mock_status, client):
    """save_mount_settings() itself raises ValueError for a bad value -- the route must surface that as a
    real error, not a 500, and must never fall through to anything that could reach rclone."""
    mock_save.side_effect = ValueError("checkers must be a positive number, got -1.")
    mock_remotes.return_value = ["gdrive"]
    mock_mounts.return_value = []
    mock_status.return_value = "connected"

    resp = client.post("/mounts/settings", data={"remote_name": "gdrive", "checkers": "-1", "tpslimit": "8"})

    assert resp.status_code == 400
    assert b"checkers must be a positive number" in resp.data


@patch("web.app.get_mount_settings")
@patch("web.app.remote_status")
@patch("web.app.list_mounts")
@patch("web.app.list_remotes")
def test_mounts_page_prefills_settings_form_with_effective_values(mock_remotes, mock_mounts, mock_status, mock_get_settings, client):
    """The settings form must show the current effective values (saved-or-default), never a blank field --
    so raising checkers/tpslimit is a deliberate choice, not a blind guess."""
    mock_remotes.return_value = ["gdrive"]
    mock_mounts.return_value = []
    mock_status.return_value = "connected"
    mock_get_settings.return_value = {"checkers": 40, "tpslimit": 20}

    resp = client.get("/mounts")

    assert resp.status_code == 200
    assert b'value="40"' in resp.data
    assert b'value="20"' in resp.data
