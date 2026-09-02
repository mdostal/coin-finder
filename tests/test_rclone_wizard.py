import configparser
from pathlib import Path
from unittest.mock import MagicMock, patch

from web.rclone_wizard import create_remote, update_remote_credentials


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


# --- update_remote_credentials() -------------------------------------------
#
# Reuses the same subprocess-mocking convention as create_remote()'s tests
# above, but with a real (tmp_path) rclone.conf on disk standing in for
# rclone's own config file -- the side_effect helpers below simulate rclone
# actually rewriting it, since the acceptance criteria this story is built
# against ("leaves exactly one remote", "not partially updated / not
# deleted") are claims about that file's real contents, not just about
# which subprocess args were used.


def _fake_rclone_config_contents(remote_name, client_id="", client_secret="", token='{"access_token":"old"}'):
    lines = [f"[{remote_name}]", "type = drive", "scope = drive.readonly"]
    if client_id:
        lines.append(f"client_id = {client_id}")
    if client_secret:
        lines.append(f"client_secret = {client_secret}")
    if token:
        lines.append(f"token = {token}")
    return "\n".join(lines) + "\n"


def _update_side_effect(config_path, remote_name, update_returncode=0, verify_returncode=0):
    """
    A subprocess.run side_effect standing in for real rclone across the
    three commands update_remote_credentials() issues: `config file`
    (returns the tmp config path), `config update` (rewrites the tmp
    config file in place -- including on failure, the realistic worst
    case, since `rclone config create` is already confirmed to write
    partial state before failing), and `lsd` (the post-update verify).
    """

    def run(args, **kwargs):
        if args[:3] == ["rclone", "config", "file"]:
            return MagicMock(returncode=0, stdout=f"Configuration file is stored at:\n{config_path}\n", stderr="")
        if args[:3] == ["rclone", "config", "update"]:
            new_client_id = args[args.index("client_id") + 1]
            new_client_secret = args[args.index("client_secret") + 1]
            Path(config_path).write_text(
                _fake_rclone_config_contents(
                    remote_name, client_id=new_client_id, client_secret=new_client_secret, token='{"access_token":"new"}'
                )
            )
            return MagicMock(returncode=update_returncode, stdout="", stderr="" if update_returncode == 0 else "boom")
        if args[:2] == ["rclone", "lsd"]:
            return MagicMock(returncode=verify_returncode, stdout="", stderr="" if verify_returncode == 0 else "googleapi: Error 401")
        return MagicMock(returncode=0, stdout="", stderr="")

    return run


@patch("web.rclone_wizard.subprocess.run")
def test_update_remote_credentials_rejects_a_client_id_that_does_not_look_like_google(mock_run):
    result = update_remote_credentials("gdrive", "mathew.dostal-drive", "shh")

    assert result["ok"] is False
    assert "apps.googleusercontent.com" in result["report"]
    mock_run.assert_not_called()


@patch("web.rclone_wizard.subprocess.run")
def test_update_remote_credentials_rejects_a_blank_client_id(mock_run):
    result = update_remote_credentials("gdrive", "", "shh")

    assert result["ok"] is False
    mock_run.assert_not_called()


@patch("web.rclone_wizard.subprocess.run")
def test_update_remote_credentials_requires_a_client_secret(mock_run):
    result = update_remote_credentials("gdrive", "123456-abc.apps.googleusercontent.com", "")

    assert result["ok"] is False
    assert "secret" in result["report"].lower()
    mock_run.assert_not_called()


@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_update_remote_credentials_refuses_an_unknown_remote(mock_list_remotes, mock_run):
    mock_list_remotes.return_value = []

    result = update_remote_credentials("gdrive", "123456-abc.apps.googleusercontent.com", "shh")

    assert result["ok"] is False
    assert "no remote named" in result["report"].lower()
    mock_run.assert_not_called()


@patch("web.rclone_wizard.resolve_vault_entries_with_values")
@patch("web.rclone_wizard.add_vault_entry")
@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_update_remote_credentials_success_leaves_exactly_one_remote(mock_list_remotes, mock_run, mock_add, mock_resolve, tmp_path):
    remote_name = "gdrive"
    config_path = tmp_path / "rclone.conf"
    config_path.write_text(_fake_rclone_config_contents(remote_name, token='{"access_token":"old"}'))

    mock_list_remotes.return_value = [remote_name]
    mock_resolve.return_value = [("rclone-gdrive-client-secret", "the-real-secret")]
    mock_run.side_effect = _update_side_effect(str(config_path), remote_name)

    result = update_remote_credentials(remote_name, "123456-abc.apps.googleusercontent.com", "shh")

    assert result["ok"] is True

    parser = configparser.ConfigParser()
    parser.read(config_path)
    assert parser.sections() == [remote_name]
    assert parser[remote_name]["client_id"] == "123456-abc.apps.googleusercontent.com"

    update_calls = [c[0][0] for c in mock_run.call_args_list if c[0][0][:3] == ["rclone", "config", "update"]]
    assert len(update_calls) == 1
    assert update_calls[0][:4] == ["rclone", "config", "update", remote_name]
    # never delete-and-recreate -- update_remote_credentials() must only ever call `config update`
    assert all(c[0][0][:3] != ["rclone", "config", "delete"] for c in mock_run.call_args_list)
    assert all(c[0][0][:3] != ["rclone", "config", "create"] for c in mock_run.call_args_list)


@patch("web.rclone_wizard.resolve_vault_entries_with_values")
@patch("web.rclone_wizard.add_vault_entry")
@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_update_remote_credentials_routes_client_secret_through_vault(mock_list_remotes, mock_run, mock_add, mock_resolve, tmp_path):
    remote_name = "gdrive"
    config_path = tmp_path / "rclone.conf"
    config_path.write_text(_fake_rclone_config_contents(remote_name))

    mock_list_remotes.return_value = [remote_name]
    mock_resolve.return_value = [("rclone-gdrive-client-secret", "the-real-secret")]
    mock_run.side_effect = _update_side_effect(str(config_path), remote_name)

    update_remote_credentials(remote_name, "123456-abc.apps.googleusercontent.com", "shh")

    mock_add.assert_called_once()
    assert mock_add.call_args[0][0] == "rclone-gdrive-client-secret"
    mock_resolve.assert_called_once_with(["rclone-gdrive-client-secret"])

    update_args = [c[0][0] for c in mock_run.call_args_list if c[0][0][:3] == ["rclone", "config", "update"]][0]
    assert "client_id" in update_args and "123456-abc.apps.googleusercontent.com" in update_args
    assert "client_secret" in update_args and "the-real-secret" in update_args
    assert "shh" not in update_args  # the raw form value never reaches the rclone call directly


@patch("web.rclone_wizard.resolve_vault_entries_with_values")
@patch("web.rclone_wizard.add_vault_entry")
@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_update_remote_credentials_restores_backup_when_verification_fails(mock_list_remotes, mock_run, mock_add, mock_resolve, tmp_path):
    remote_name = "gdrive"
    config_path = tmp_path / "rclone.conf"
    original_contents = _fake_rclone_config_contents(remote_name, token='{"access_token":"old"}')
    config_path.write_text(original_contents)

    mock_list_remotes.return_value = [remote_name]
    mock_resolve.return_value = [("rclone-gdrive-client-secret", "the-real-secret")]
    mock_run.side_effect = _update_side_effect(str(config_path), remote_name, verify_returncode=1)

    result = update_remote_credentials(remote_name, "123456-abc.apps.googleusercontent.com", "shh")

    assert result["ok"] is False
    assert config_path.read_text() == original_contents  # byte-for-byte restored, including the old token

    parser = configparser.ConfigParser()
    parser.read(config_path)
    assert parser.sections() == [remote_name]  # not deleted
    assert "client_id" not in parser[remote_name]  # not left half-updated either


@patch("web.rclone_wizard.resolve_vault_entries_with_values")
@patch("web.rclone_wizard.add_vault_entry")
@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_update_remote_credentials_restores_backup_when_update_command_fails(mock_list_remotes, mock_run, mock_add, mock_resolve, tmp_path):
    """
    Simulates the realistic worst case (already confirmed true of `rclone
    config create` for this project): the update command rewrites the
    config file before it reports failure. The remote must come back
    byte-for-byte, not just "not deleted".
    """
    remote_name = "gdrive"
    config_path = tmp_path / "rclone.conf"
    original_contents = _fake_rclone_config_contents(remote_name, token='{"access_token":"old"}')
    config_path.write_text(original_contents)

    mock_list_remotes.return_value = [remote_name]
    mock_resolve.return_value = [("rclone-gdrive-client-secret", "the-real-secret")]
    mock_run.side_effect = _update_side_effect(str(config_path), remote_name, update_returncode=1)

    result = update_remote_credentials(remote_name, "123456-abc.apps.googleusercontent.com", "shh")

    assert result["ok"] is False
    assert "boom" in result["report"]
    assert config_path.read_text() == original_contents


@patch("web.rclone_wizard.resolve_vault_entries_with_values")
@patch("web.rclone_wizard.add_vault_entry")
@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_update_remote_credentials_restores_backup_on_timeout(mock_list_remotes, mock_run, mock_add, mock_resolve, tmp_path):
    from subprocess import TimeoutExpired

    remote_name = "gdrive"
    config_path = tmp_path / "rclone.conf"
    original_contents = _fake_rclone_config_contents(remote_name, token='{"access_token":"old"}')
    config_path.write_text(original_contents)

    mock_list_remotes.return_value = [remote_name]
    mock_resolve.return_value = [("rclone-gdrive-client-secret", "the-real-secret")]

    def run(args, **kwargs):
        if args[:3] == ["rclone", "config", "file"]:
            return MagicMock(returncode=0, stdout=f"Configuration file is stored at:\n{config_path}\n", stderr="")
        if args[:3] == ["rclone", "config", "update"]:
            raise TimeoutExpired(cmd=args, timeout=300)
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_run.side_effect = run

    result = update_remote_credentials(remote_name, "123456-abc.apps.googleusercontent.com", "shh")

    assert result["ok"] is False
    assert "Timed out" in result["report"]
    assert config_path.read_text() == original_contents


@patch("web.rclone_wizard.resolve_vault_entries_with_values")
@patch("web.rclone_wizard.add_vault_entry")
@patch("web.rclone_wizard.subprocess.run")
@patch("web.rclone_wizard.list_remotes")
def test_update_remote_credentials_reports_progress(mock_list_remotes, mock_run, mock_add, mock_resolve, tmp_path):
    remote_name = "gdrive"
    config_path = tmp_path / "rclone.conf"
    config_path.write_text(_fake_rclone_config_contents(remote_name))

    mock_list_remotes.return_value = [remote_name]
    mock_resolve.return_value = [("rclone-gdrive-client-secret", "the-real-secret")]
    mock_run.side_effect = _update_side_effect(str(config_path), remote_name)

    calls = []
    update_remote_credentials(
        remote_name, "123456-abc.apps.googleusercontent.com", "shh",
        progress_callback=lambda current, total, message="": calls.append((current, total, message)),
    )

    assert len(calls) == 5  # backup, vault, updating, verifying, done
    assert calls[-1][0] == calls[-1][1]  # final call's current == total
