from unittest.mock import MagicMock, patch

from web.rclone_wizard import create_remote


@patch("web.rclone_wizard.list_remotes")
def test_create_remote_refuses_duplicate_name(mock_list_remotes):
    mock_list_remotes.return_value = ["gdrive"]

    result = create_remote("gdrive")

    assert result["ok"] is False
    assert "already exists" in result["report"]


@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_create_remote_runs_rclone_config_create(mock_list_remotes, mock_run):
    mock_list_remotes.return_value = []
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    result = create_remote("gdrive", kind="gdrive", scope="drive.readonly")

    assert result["ok"] is True
    args = mock_run.call_args[0][0]
    assert args[:5] == ["rclone", "config", "create", "gdrive", "drive"]
    assert "scope" in args and "drive.readonly" in args
    assert "--non-interactive" not in args


@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_create_remote_selects_gcs_backend(mock_list_remotes, mock_run):
    mock_list_remotes.return_value = []
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    create_remote("bucket1", kind="gcs")

    args = mock_run.call_args[0][0]
    assert "google cloud storage" in args


@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_create_remote_reports_rclone_failure(mock_list_remotes, mock_run):
    mock_list_remotes.return_value = []
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")

    result = create_remote("gdrive")

    assert result["ok"] is False
    assert "boom" in result["report"]


@patch("web.rclone_wizard.resolve_vault_entries_with_values")
@patch("web.rclone_wizard.add_vault_entry")
@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_create_remote_routes_client_secret_through_vault(mock_list_remotes, mock_run, mock_add, mock_resolve):
    mock_list_remotes.return_value = []
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    mock_resolve.return_value = [("rclone-gdrive-client-secret", "the-real-secret")]

    create_remote("gdrive", client_id="abc123", client_secret="shh")

    mock_add.assert_called_once()
    assert mock_add.call_args[0][0] == "rclone-gdrive-client-secret"
    mock_resolve.assert_called_once_with(["rclone-gdrive-client-secret"])

    args = mock_run.call_args[0][0]
    assert "client_id" in args and "abc123" in args
    assert "client_secret" in args and "the-real-secret" in args
    assert "shh" not in args  # the raw form value never reaches the rclone call directly


@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_create_remote_skips_vault_when_no_credentials_given(mock_list_remotes, mock_run):
    mock_list_remotes.return_value = []
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    create_remote("gdrive")

    args = mock_run.call_args[0][0]
    assert "client_id" not in args
    assert "client_secret" not in args


@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_create_remote_reports_timeout(mock_list_remotes, mock_run):
    mock_list_remotes.return_value = []
    from subprocess import TimeoutExpired

    mock_run.side_effect = TimeoutExpired(cmd=["rclone"], timeout=300)

    result = create_remote("gdrive")

    assert result["ok"] is False
    assert "Timed out" in result["report"]


@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_create_remote_reports_progress(mock_list_remotes, mock_run):
    mock_list_remotes.return_value = []
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    calls = []
    create_remote("gdrive", progress_callback=lambda current, total, message="": calls.append((current, total, message)))

    assert len(calls) == 2
    assert calls[-1][0] == 3
