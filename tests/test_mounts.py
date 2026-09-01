import json
import subprocess as subprocess_module
from pathlib import Path
from unittest.mock import MagicMock, patch

# Imported under an alias: pytest would otherwise try to collect and run
# `test_mount` itself as a test function (its name matches the `test_*`
# collection pattern) since importing it binds that exact name at module
# scope here.
from web.mounts import install_rclone, is_mounted, is_rclone_installed, list_mounts, list_remotes, mount, remote_status, remove_remote, unmount
from web.mounts import test_mount as run_test_mount


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
def test_mount_starts_rclone_nfsmount_read_only(mock_popen, tmp_path):
    """
    Regression test for a real bug hit live: `rclone mount` fails
    immediately on macOS via Homebrew ("rclone mount is not supported on
    MacOS when rclone is installed via Homebrew") -- confirmed via direct
    reproduction. `rclone nfsmount` (same binary, no macFUSE needed)
    works, verified live against a real Google Drive remote.
    """
    mock_popen.return_value = MagicMock(pid=12345)
    state_path = tmp_path / "mounts_state.json"
    mount_point = tmp_path / "mnt"

    mount("gdrive", str(mount_point), state_path=state_path, log_dir=tmp_path)

    args = mock_popen.call_args[0][0]
    assert "rclone" in args
    assert "nfsmount" in args
    assert "mount" not in args  # the broken subcommand must never be used
    assert "--read-only" in args
    assert mount_point.exists()


@patch("web.mounts.subprocess.Popen")
def test_mount_tunes_checkers_and_skips_dangling_shortcuts(mock_popen, tmp_path):
    """
    Regression test for two real, sequential live incidents on the same
    mount. First: a `find` job over a large (6TB) real Google Drive mount
    ran for 10+ hours with rclone's default --checkers 8, no visible
    progress, mount log clean -- too little listing concurrency for the
    drive's real size. --checkers 32 fixed that, but then overshot: this
    remote authenticates through rclone's own shared default Google API
    client (no client_id/client_secret configured), and 32 concurrent
    listers against a big/deep tree tripped that shared client's Drive
    API quota -- real, repeated 403 "Queries per minute" errors in the
    mount log, each one silently dropping an entire subtree's listing.
    --checkers 16 plus --tpslimit 8 self-paces under the shared quota
    instead of bursting into 403s and backing off after the fact.
    --drive-skip-dangling-shortcuts (a handful of broken shortcuts on
    this real Drive were getting needlessly re-resolved on every
    directory cache refresh) is unchanged.
    """
    mock_popen.return_value = MagicMock(pid=12345)
    state_path = tmp_path / "mounts_state.json"
    mount_point = tmp_path / "mnt"

    mount("gdrive", str(mount_point), state_path=state_path, log_dir=tmp_path)

    args = mock_popen.call_args[0][0]
    assert "--checkers" in args
    assert args[args.index("--checkers") + 1] == "16"
    assert "--tpslimit" in args
    assert args[args.index("--tpslimit") + 1] == "8"
    assert "--drive-skip-dangling-shortcuts" in args


@patch("web.mounts.subprocess.Popen")
def test_mount_captures_stderr_to_a_log_file_not_devnull(mock_popen, tmp_path):
    mock_popen.return_value = MagicMock(pid=12345)
    state_path = tmp_path / "mounts_state.json"
    mount_point = tmp_path / "mnt"

    mount("gdrive", str(mount_point), state_path=state_path, log_dir=tmp_path)

    kwargs = mock_popen.call_args[1]
    assert kwargs["stderr"] != subprocess_module.DEVNULL

    state = json.loads(state_path.read_text())
    assert "log_path" in state["gdrive"]
    assert Path(state["gdrive"]["log_path"]).parent == tmp_path


@patch("web.mounts.subprocess.run")
def test_unmount_tries_diskutil_unmount_first(mock_run, tmp_path):
    """
    Regression test for a real failure hit live: plain `umount` refused
    this NFS-served mount with "Resource busy -- try 'diskutil unmount'"
    even with nothing reading from it -- the state entry got dropped
    anyway (since the old code never checked the return code), leaving
    the app's own tracking out of sync with a mount that was still very
    much alive.
    """
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    state_path = tmp_path / "mounts_state.json"
    state_path.write_text(json.dumps({"gdrive": {"pid": 1, "mount_point": "/tmp/mnt", "started_at": 0, "log_path": "/tmp/x.log"}}))

    unmount("gdrive", state_path=state_path)

    args = mock_run.call_args_list[0][0][0]
    assert args[0] == "diskutil"
    assert args[1] == "unmount"
    assert "/tmp/mnt" in args


@patch("web.mounts.subprocess.run")
def test_unmount_falls_back_to_plain_umount_when_diskutil_fails(mock_run, tmp_path):
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="some error")
    state_path = tmp_path / "mounts_state.json"
    state_path.write_text(json.dumps({"gdrive": {"pid": 1, "mount_point": "/tmp/mnt", "started_at": 0, "log_path": "/tmp/x.log"}}))

    unmount("gdrive", state_path=state_path)

    assert mock_run.call_count == 2
    second_call_args = mock_run.call_args_list[1][0][0]
    assert second_call_args[0] == "umount"


@patch("web.mounts.os.listdir")
@patch("web.mounts.os.kill")
@patch("web.mounts.subprocess.Popen")
def test_is_mounted_true_when_process_alive_and_mount_point_readable(mock_popen, mock_kill, mock_listdir, tmp_path):
    mock_popen.return_value = MagicMock(pid=12345)
    mock_listdir.return_value = ["some_file.txt"]
    state_path = tmp_path / "mounts_state.json"

    mount("gdrive", str(tmp_path / "mnt"), state_path=state_path, log_dir=tmp_path)

    assert is_mounted("gdrive", state_path=state_path) is True


@patch("web.mounts.os.kill")
@patch("web.mounts.subprocess.Popen")
def test_is_mounted_false_when_process_is_dead(mock_popen, mock_kill, tmp_path):
    mock_popen.return_value = MagicMock(pid=12345)
    mock_kill.side_effect = OSError("no such process")
    state_path = tmp_path / "mounts_state.json"

    mount("gdrive", str(tmp_path / "mnt"), state_path=state_path, log_dir=tmp_path)

    assert is_mounted("gdrive", state_path=state_path) is False


def test_is_mounted_false_for_unknown_remote(tmp_path):
    assert is_mounted("nope", state_path=tmp_path / "mounts_state.json") is False


@patch("web.mounts.subprocess.run")
@patch("web.mounts.os.kill")
@patch("web.mounts.subprocess.Popen")
def test_unmount_removes_state_entry(mock_popen, mock_kill, mock_run, tmp_path):
    mock_popen.return_value = MagicMock(pid=12345)
    state_path = tmp_path / "mounts_state.json"
    mount("gdrive", str(tmp_path / "mnt"), state_path=state_path, log_dir=tmp_path)

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

    mount("gdrive", str(mount_point), state_path=state_path, log_dir=tmp_path)

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


# --- test_mount() ------------------------------------------------------
#
# gmc-02: a bounded, real "does this remote actually hold up" check the
# user can run instead of starting a real find/check-balances job and
# waiting to find out. Every real subprocess call (Popen, run) is mocked
# -- no real rclone or Google API calls, and no real mount points are
# ever created on this machine (the "mount point" test_mount() creates
# via tempfile.mkdtemp is a real local temp dir, which is fine and
# always cleaned up -- it's the FUSE mount subprocess itself that's
# mocked out). `time.sleep` is also mocked so tests never actually wait
# out the fixed attach grace or any timeout.


@patch("web.mounts.subprocess.run")
@patch("web.mounts.subprocess.Popen")
@patch("web.mounts.time.sleep")
def test_test_mount_success_reports_pass_and_leaves_nothing_mounted(mock_sleep, mock_popen, mock_run, tmp_path):
    """
    A successful test reports pass + real detail (what was actually
    listed, not a bare boolean) and leaves nothing mounted afterward --
    unlike mount(), which leaves a mount running, test_mount() always
    tears its own throwaway mount back down before returning.
    """
    proc = MagicMock()
    proc.poll.return_value = None  # still running -- the mount attempt "succeeded"
    mock_popen.return_value = proc

    def run_side_effect(args, **kwargs):
        if args[0] == "ls":
            return MagicMock(returncode=0, stdout="total 8\nfile1.txt\nfile2.txt\n", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")  # diskutil unmount

    mock_run.side_effect = run_side_effect

    result = run_test_mount("gdrive", log_dir=tmp_path)

    assert result["ok"] is True
    assert "PASS" in result["report"]
    assert "2 entries" in result["report"]

    mount_point = Path(mock_popen.call_args[0][0][3])
    assert not mount_point.exists()  # throwaway dir cleaned up, never left behind

    unmount_calls = [c[0][0] for c in mock_run.call_args_list if c[0][0][:2] == ["diskutil", "unmount"]]
    assert len(unmount_calls) == 1
    assert unmount_calls[0][2] == str(mount_point)

    # never the user's real configured mount point -- always a throwaway one
    assert "coin-finder-test-mount-gdrive-" in str(mount_point)


@patch("web.mounts.subprocess.run")
@patch("web.mounts.subprocess.Popen")
@patch("web.mounts.time.sleep")
def test_test_mount_surfaces_real_rclone_error_text(mock_sleep, mock_popen, mock_run, tmp_path):
    """
    A real rclone failure (simulated here via a nonexistent remote name,
    which makes rclone exit immediately with a real config-lookup error)
    must surface rclone's actual error text, not a generic failure
    message -- the same "don't discard real diagnostics" principle the
    nfsmount-fix epic already established for the real mount path.
    """

    def popen_side_effect(args, stdout=None, stderr=None):
        stderr.write('Failed to create file system for "nonexistent:": didn\'t find section in config file\n')
        stderr.flush()
        proc = MagicMock()
        proc.poll.return_value = 1  # rclone already exited -- the mount attempt failed
        return proc

    mock_popen.side_effect = popen_side_effect
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")  # diskutil unmount cleanup

    result = run_test_mount("nonexistent", log_dir=tmp_path)

    assert result["ok"] is False
    assert "didn't find section in config file" in result["report"]


@patch("web.mounts.subprocess.run")
@patch("web.mounts.subprocess.Popen")
@patch("web.mounts.time.sleep")
def test_test_mount_times_out_instead_of_blocking_forever_on_a_wedged_read(mock_sleep, mock_popen, mock_run, tmp_path):
    """
    Regression coverage for the exact failure mode is_mounted()'s own
    unbounded os.listdir() suffers from: the read against a wedged FUSE
    mount must time out, not hang the caller forever. Enforced here via
    subprocess.run's own `timeout=` (simulated via TimeoutExpired) --
    no real waiting happens in this test (time.sleep is mocked, and
    TimeoutExpired is raised synchronously by the mock rather than after
    any real delay).
    """
    proc = MagicMock()
    proc.poll.return_value = None  # process alive -- the mount step "succeeded"
    mock_popen.return_value = proc

    def run_side_effect(args, **kwargs):
        if args[0] == "ls":
            raise subprocess_module.TimeoutExpired(cmd=args, timeout=kwargs.get("timeout"))
        return MagicMock(returncode=0, stdout="", stderr="")  # diskutil unmount cleanup

    mock_run.side_effect = run_side_effect

    result = run_test_mount("gdrive", timeout=5, log_dir=tmp_path)

    assert result["ok"] is False
    assert "did not finish" in result["report"] or "timed out" in result["report"].lower()

    # the request thread was never blocked on the wedged process itself --
    # it's force-terminated as part of cleanup, not left running.
    proc.terminate.assert_called_once()


@patch("web.mounts.subprocess.run")
@patch("web.mounts.subprocess.Popen")
@patch("web.mounts.time.sleep")
def test_test_mount_always_unmounts_even_when_the_read_fails(mock_sleep, mock_popen, mock_run, tmp_path):
    """The finally-block unmount must run on every exit path, not just the success path."""
    proc = MagicMock()
    proc.poll.return_value = None
    mock_popen.return_value = proc

    def run_side_effect(args, **kwargs):
        if args[0] == "ls":
            return MagicMock(returncode=1, stdout="", stderr="ls: cannot access: Input/output error")
        return MagicMock(returncode=0, stdout="", stderr="")

    mock_run.side_effect = run_side_effect

    result = run_test_mount("gdrive", log_dir=tmp_path)

    assert result["ok"] is False
    assert "Input/output error" in result["report"]

    unmount_calls = [c[0][0] for c in mock_run.call_args_list if c[0][0][:2] == ["diskutil", "unmount"]]
    assert len(unmount_calls) == 1


@patch("web.mounts.subprocess.run")
@patch("web.mounts.subprocess.Popen")
@patch("web.mounts.time.sleep")
def test_test_mount_reports_when_rclone_is_not_installed(mock_sleep, mock_popen, mock_run, tmp_path):
    mock_popen.side_effect = FileNotFoundError()
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")  # diskutil unmount cleanup (a no-op here)

    result = run_test_mount("gdrive", log_dir=tmp_path)

    assert result["ok"] is False
    assert "rclone isn't installed" in result["report"]
