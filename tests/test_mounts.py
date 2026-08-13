from unittest.mock import MagicMock, patch

from web.mounts import is_mounted, list_mounts, list_remotes, mount, unmount


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
