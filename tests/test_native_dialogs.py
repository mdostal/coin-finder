from unittest.mock import MagicMock, patch

import pytest

from web.native_dialogs import pick_path


@patch("web.native_dialogs.subprocess.run")
@patch("web.native_dialogs.platform.system", return_value="Darwin")
def test_pick_path_macos_file_returns_stripped_path(mock_system, mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="/Users/x/wallet.dat\n")

    result = pick_path(mode="file")

    assert result == "/Users/x/wallet.dat"
    args = mock_run.call_args.args[0]
    assert "osascript" in args
    assert any("choose file" in a for a in args)


@patch("web.native_dialogs.subprocess.run")
@patch("web.native_dialogs.platform.system", return_value="Darwin")
def test_pick_path_macos_directory_uses_choose_folder(mock_system, mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="/Users/x/Drive\n")

    result = pick_path(mode="directory")

    assert result == "/Users/x/Drive"
    args = mock_run.call_args.args[0]
    assert any("choose folder" in a for a in args)


@patch("web.native_dialogs.subprocess.run")
@patch("web.native_dialogs.platform.system", return_value="Darwin")
def test_pick_path_macos_cancel_returns_none(mock_system, mock_run):
    mock_run.return_value = MagicMock(returncode=1, stdout="")

    assert pick_path(mode="file") is None


@patch("web.native_dialogs.shutil.which", return_value="/usr/bin/zenity")
@patch("web.native_dialogs.subprocess.run")
@patch("web.native_dialogs.platform.system", return_value="Linux")
def test_pick_path_linux_directory_passes_directory_flag(mock_system, mock_run, mock_which):
    mock_run.return_value = MagicMock(returncode=0, stdout="/home/x/Drive\n")

    result = pick_path(mode="directory")

    assert result == "/home/x/Drive"
    args = mock_run.call_args.args[0]
    assert "--directory" in args


@patch("web.native_dialogs.shutil.which", return_value=None)
@patch("web.native_dialogs.platform.system", return_value="Linux")
def test_pick_path_linux_without_zenity_raises(mock_system, mock_which):
    with pytest.raises(RuntimeError):
        pick_path(mode="file")


@patch("web.native_dialogs.platform.system", return_value="Windows")
def test_pick_path_unsupported_platform_raises(mock_system):
    with pytest.raises(RuntimeError):
        pick_path(mode="file")
