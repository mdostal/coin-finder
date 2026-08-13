import os
import stat
import subprocess

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "install_rclone.sh")


def _make_fake_brew(bin_dir):
    fake_brew = os.path.join(bin_dir, "brew")
    with open(fake_brew, "w") as f:
        f.write("#!/usr/bin/env bash\necho \"fake brew: $@\"\nexit 0\n")
    os.chmod(fake_brew, os.stat(fake_brew).st_mode | stat.S_IEXEC)


def test_script_prints_macfuse_manual_approval_callout(tmp_path):
    _make_fake_brew(str(tmp_path))
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env['PATH']}"

    result = subprocess.run(
        ["bash", SCRIPT],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    assert "macFUSE requires manual approval" in result.stdout
    assert "System Settings" in result.stdout


def test_script_calls_brew_install_rclone_and_macfuse_cask(tmp_path):
    _make_fake_brew(str(tmp_path))
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env['PATH']}"

    result = subprocess.run(["bash", SCRIPT], capture_output=True, text=True, env=env)

    assert "fake brew: install rclone" in result.stdout
    assert "fake brew: install --cask macfuse" in result.stdout
