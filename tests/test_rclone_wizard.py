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
    create_args = mock_run.call_args_list[0][0][0]
    assert create_args[:5] == ["rclone", "config", "create", "gdrive", "drive"]
    assert "scope" in create_args and "drive.readonly" in create_args
    assert "--non-interactive" not in create_args


@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_create_remote_verifies_after_create(mock_list_remotes, mock_run):
    mock_list_remotes.return_value = []
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    create_remote("gdrive")

    verify_args = mock_run.call_args_list[1][0][0]
    assert verify_args[:3] == ["rclone", "lsd", "gdrive:"]


@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_create_remote_selects_gcs_backend(mock_list_remotes, mock_run):
    mock_list_remotes.return_value = []
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    create_remote("bucket1", kind="gcs")

    create_args = mock_run.call_args_list[0][0][0]
    assert "google cloud storage" in create_args


@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_create_remote_reports_rclone_create_failure(mock_list_remotes, mock_run):
    mock_list_remotes.return_value = []
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")

    result = create_remote("gdrive")

    assert result["ok"] is False
    assert "boom" in result["report"]


@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_create_remote_deletes_partial_remote_on_create_failure(mock_list_remotes, mock_run):
    mock_list_remotes.return_value = []
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")

    create_remote("gdrive")

    delete_args = mock_run.call_args_list[-1][0][0]
    assert delete_args == ["rclone", "config", "delete", "gdrive"]


@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_create_remote_reports_and_cleans_up_when_verification_fails(mock_list_remotes, mock_run):
    """
    The real bug this story fixes: `rclone config create` can exit 0
    while the OAuth handshake never actually completed (confirmed live
    -- two real, permanently-broken, tokenless remotes existed exactly
    this way). The verification read must catch this and clean up.
    """
    mock_list_remotes.return_value = []

    def run(args, **kwargs):
        if args[:2] == ["rclone", "config"] and "create" in args:
            return MagicMock(returncode=0, stdout="", stderr="")
        if args[:2] == ["rclone", "lsd"]:
            return MagicMock(returncode=1, stdout="", stderr="couldn't list directory: googleapi: Error 401")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_run.side_effect = run

    result = create_remote("gdrive")

    assert result["ok"] is False
    assert "didn't actually" in result["report"].lower() or "sign-in" in result["report"].lower()
    delete_calls = [c for c in mock_run.call_args_list if c[0][0][:3] == ["rclone", "config", "delete"]]
    assert len(delete_calls) == 1
    assert delete_calls[0][0][0] == ["rclone", "config", "delete", "gdrive"]


@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_create_remote_does_not_delete_on_full_success(mock_list_remotes, mock_run):
    mock_list_remotes.return_value = []
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    create_remote("gdrive")

    delete_calls = [c for c in mock_run.call_args_list if c[0][0][:3] == ["rclone", "config", "delete"]]
    assert delete_calls == []


@patch("web.rclone_wizard.subprocess.run")
def test_create_remote_rejects_a_client_id_that_does_not_look_like_google(mock_run):
    result = create_remote("gdrive", client_id="mathew.dostal-drive", client_secret="whatever")

    assert result["ok"] is False
    assert "apps.googleusercontent.com" in result["report"]
    mock_run.assert_not_called()


@patch("web.rclone_wizard.resolve_vault_entries_with_values")
@patch("web.rclone_wizard.add_vault_entry")
@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_create_remote_accepts_a_real_looking_google_client_id(mock_list_remotes, mock_run, mock_add, mock_resolve):
    mock_list_remotes.return_value = []
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    mock_resolve.return_value = [("rclone-gdrive-client-secret", "the-real-secret")]

    result = create_remote("gdrive", client_id="123456-abc.apps.googleusercontent.com", client_secret="shh")

    assert result["ok"] is True


@patch("web.rclone_wizard.resolve_vault_entries_with_values")
@patch("web.rclone_wizard.add_vault_entry")
@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_create_remote_routes_client_secret_through_vault(mock_list_remotes, mock_run, mock_add, mock_resolve):
    mock_list_remotes.return_value = []
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    mock_resolve.return_value = [("rclone-gdrive-client-secret", "the-real-secret")]

    create_remote("gdrive", client_id="123456-abc.apps.googleusercontent.com", client_secret="shh")

    mock_add.assert_called_once()
    assert mock_add.call_args[0][0] == "rclone-gdrive-client-secret"
    mock_resolve.assert_called_once_with(["rclone-gdrive-client-secret"])

    create_args = mock_run.call_args_list[0][0][0]
    assert "client_id" in create_args and "123456-abc.apps.googleusercontent.com" in create_args
    assert "client_secret" in create_args and "the-real-secret" in create_args
    assert "shh" not in create_args  # the raw form value never reaches the rclone call directly


@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_create_remote_skips_vault_when_no_credentials_given(mock_list_remotes, mock_run):
    mock_list_remotes.return_value = []
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    create_remote("gdrive")

    create_args = mock_run.call_args_list[0][0][0]
    assert "client_id" not in create_args
    assert "client_secret" not in create_args


@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_create_remote_reports_timeout(mock_list_remotes, mock_run):
    mock_list_remotes.return_value = []
    from subprocess import TimeoutExpired

    # The create call times out; the cleanup delete call that follows must
    # not itself raise -- only the FIRST call (create) times out.
    mock_run.side_effect = [TimeoutExpired(cmd=["rclone"], timeout=300), MagicMock(returncode=0, stdout="", stderr="")]

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

    assert len(calls) == 3  # opening browser, verifying, done
    assert calls[-1][0] == calls[-1][1]  # final call's current == total
