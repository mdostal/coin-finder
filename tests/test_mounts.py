from unittest.mock import MagicMock, patch

from web.mounts import install_rclone, is_mounted, is_rclone_installed, list_mounts, list_remotes, mount, remote_status, remove_remote, unmount


@patch("web.mounts.subprocess.run")
def test_list_remotes_parses_rclone_output(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="gdrive:\nmybucket:\n")

    remotes = list_remotes()

    assert remotes == ["gdrive", "mybucket"]


@patch("web.mounts.subprocess.run")
def test_list_remotes_returns_empty_on_failure(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stdout="")
    assert list_remotes() == []


@patch("web.mounts.subprocess.Popen")
def test_mount_starts_rclone_read_only(mock_popen, tmp_path):
    mock_popen.return_value = MagicMock(pid=12345)
    state_path = tmp_path / "mounts_state.json"
    mount_point = tmp_path / "mnt"

    mount("gdrive", str(mount_point), state_path=state_path)

    args = mock_popen.call_args[0][0]
    assert "rclone" in args
    assert "mount" in args
    assert "--read-only" in args
    assert mount_point.exists()


@patch("web.mounts.os.listdir")
@patch("web.mounts.os.kill")
@patch("web.mounts.subprocess.Popen")
def test_is_mounted_true_when_process_alive_and_mount_point_readable(mock_popen, mock_kill, mock_listdir, tmp_path):
    mock_popen.return_value = MagicMock(pid=12345)
    mock_listdir.return_value = ["some_file.txt"]
    state_path = tmp_path / "mounts_state.json"

    mount("gdrive", str(tmp_path / "mnt"), state_path=state_path)

    assert is_mounted("gdrive", state_path=state_path) is True


@patch("web.mounts.os.kill")
@patch("web.mounts.subprocess.Popen")
def test_is_mounted_false_when_process_is_dead(mock_popen, mock_kill, tmp_path):
    mock_popen.return_value = MagicMock(pid=12345)
    mock_kill.side_effect = OSError("no such process")
    state_path = tmp_path / "mounts_state.json"

    mount("gdrive", str(tmp_path / "mnt"), state_path=state_path)

    assert is_mounted("gdrive", state_path=state_path) is False


def test_is_mounted_false_for_unknown_remote(tmp_path):
    assert is_mounted("nope", state_path=tmp_path / "mounts_state.json") is False


@patch("web.mounts.subprocess.run")
@patch("web.mounts.os.kill")
@patch("web.mounts.subprocess.Popen")
def test_unmount_removes_state_entry(mock_popen, mock_kill, mock_run, tmp_path):
    mock_popen.return_value = MagicMock(pid=12345)
    state_path = tmp_path / "mounts_state.json"
    mount("gdrive", str(tmp_path / "mnt"), state_path=state_path)

    unmount("gdrive", state_path=state_path)

    assert list_mounts(state_path=state_path) == []


@patch("web.mounts.os.listdir")
@patch("web.mounts.os.kill")
@patch("web.mounts.subprocess.Popen")
def test_list_mounts_reflects_is_mounted_health(mock_popen, mock_kill, mock_listdir, tmp_path):
    mock_popen.return_value = MagicMock(pid=12345)
    mock_listdir.return_value = []
    state_path = tmp_path / "mounts_state.json"
    mount_point = tmp_path / "mnt"

    mount("gdrive", str(mount_point), state_path=state_path)

    mounts = list_mounts(state_path=state_path)
    assert len(mounts) == 1
    assert mounts[0]["remote_name"] == "gdrive"
    assert mounts[0]["is_mounted"] is True


@patch("web.mounts.shutil.which")
def test_is_rclone_installed_true_when_binary_on_path(mock_which):
    mock_which.return_value = "/opt/homebrew/bin/rclone"
    assert is_rclone_installed() is True


@patch("web.mounts.shutil.which")
def test_is_rclone_installed_false_when_not_on_path(mock_which):
    mock_which.return_value = None
    assert is_rclone_installed() is False


@patch("web.mounts.shutil.which")
@patch("web.mounts.subprocess.run")
def test_install_rclone_requires_homebrew(mock_run, mock_which):
    mock_which.return_value = None  # no brew

    result = install_rclone()

    assert result["ok"] is False
    assert "Homebrew" in result["report"]
    mock_run.assert_not_called()


@patch("web.mounts.shutil.which")
@patch("web.mounts.subprocess.run")
def test_install_rclone_runs_both_brew_installs(mock_run, mock_which):
    mock_which.side_effect = lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None
    mock_run.return_value = MagicMock(returncode=0, stdout="installed", stderr="")

    result = install_rclone()

    assert result["ok"] is True
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert ["brew", "install", "rclone"] in calls
    assert ["brew", "install", "--cask", "macfuse"] in calls
    assert "macFUSE" in result["report"]
    assert "System Settings" in result["report"]


@patch("web.mounts.shutil.which")
@patch("web.mounts.subprocess.run")
def test_install_rclone_reports_failure_without_raising(mock_run, mock_which):
    mock_which.side_effect = lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="some brew error")

    result = install_rclone()

    assert result["ok"] is False
    assert "some brew error" in result["report"]


@patch("web.mounts.shutil.which")
@patch("web.mounts.subprocess.run")
def test_install_rclone_reports_progress(mock_run, mock_which):
    mock_which.side_effect = lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    calls = []
    install_rclone(progress_callback=lambda current, total, message="": calls.append((current, total, message)))

    assert len(calls) == 2
    assert calls[0][0] == 1 and calls[1][0] == 2


@patch("web.mounts.subprocess.run")
def test_remote_status_connected_when_token_present(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="[gdrive]\ntype = drive\ntoken = {\"access_token\":\"x\"}\n", stderr="")

    assert remote_status("gdrive") == "connected"


@patch("web.mounts.subprocess.run")
def test_remote_status_incomplete_when_no_token(mock_run):
    """
    The exact real bug this session: a remote whose OAuth never finished
    has a config section but no token field.
    """
    mock_run.return_value = MagicMock(returncode=0, stdout="[gdrive]\ntype = drive\nscope = drive.readonly\n", stderr="")

    assert remote_status("gdrive") == "incomplete"


@patch("web.mounts.subprocess.run")
def test_remote_status_incomplete_on_nonzero_exit(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")

    assert remote_status("does-not-exist") == "incomplete"


@patch("web.mounts.subprocess.run")
def test_remove_remote_deletes_config(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    remove_remote("gdrive", state_path="/tmp/does-not-matter-for-this-test.json")

    delete_calls = [c for c in mock_run.call_args_list if c[0][0][:3] == ["rclone", "config", "delete"]]
    assert len(delete_calls) == 1
    assert delete_calls[0][0][0] == ["rclone", "config", "delete", "gdrive"]


@patch("web.mounts.unmount")
@patch("web.mounts.is_mounted")
@patch("web.mounts.subprocess.run")
def test_remove_remote_unmounts_first_when_currently_mounted(mock_run, mock_is_mounted, mock_unmount, tmp_path):
    mock_is_mounted.return_value = True
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    state_path = tmp_path / "mounts_state.json"

    remove_remote("gdrive", state_path=state_path)

    mock_unmount.assert_called_once_with("gdrive", state_path=state_path)


@patch("web.mounts.unmount")
@patch("web.mounts.is_mounted")
@patch("web.mounts.subprocess.run")
def test_remove_remote_skips_unmount_when_not_mounted(mock_run, mock_is_mounted, mock_unmount, tmp_path):
    mock_is_mounted.return_value = False
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    state_path = tmp_path / "mounts_state.json"

    remove_remote("gdrive", state_path=state_path)

    mock_unmount.assert_not_called()
