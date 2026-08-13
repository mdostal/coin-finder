import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from tools.unlock_wallet import find_btcrecover_script, run_unlock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR_SCRIPT = os.path.join(REPO_ROOT, "vendor", "btcrecover", "btcrecover.py")
TEST_WALLET = os.path.join(
    REPO_ROOT, "vendor", "btcrecover", "btcrecover", "test", "test-wallets", "bitcoincore-wallet.dat"
)

# Publicly documented in BTCRecover's own open-source test code
# (btcrecover/test/test_passwords.py) as the default correct password for
# bitcoincore-wallet.dat -- a deliberately fake test wallet with no real
# funds, not a real secret.
TEST_PASSWORD = "btcr-test-password"

requires_vendor = pytest.mark.skipif(
    not os.path.exists(VENDOR_SCRIPT),
    reason="vendor/btcrecover not installed -- run scripts/install_btcrecover.sh first",
)


@patch("tools.unlock_wallet.check_network_status")
def test_run_unlock_refuses_when_online_without_allow_online(mock_status):
    mock_status.return_value = "ONLINE"

    with patch("tools.unlock_wallet.subprocess.run") as mock_run:
        with pytest.raises(RuntimeError):
            run_unlock("wallet.dat", "candidates.txt", btcrecover_script="fake.py")
        mock_run.assert_not_called()


@patch("tools.unlock_wallet.check_network_status")
def test_run_unlock_refuses_when_status_unknown_without_allow_online(mock_status):
    mock_status.return_value = "UNKNOWN"

    with patch("tools.unlock_wallet.subprocess.run") as mock_run:
        with pytest.raises(RuntimeError):
            run_unlock("wallet.dat", "candidates.txt", btcrecover_script="fake.py")
        mock_run.assert_not_called()


@patch("tools.unlock_wallet.check_network_status")
def test_run_unlock_proceeds_when_offline(mock_status):
    mock_status.return_value = "OFFLINE"

    with patch("tools.unlock_wallet.subprocess.run") as mock_run:
        run_unlock("wallet.dat", "candidates.txt", btcrecover_script="fake.py")
        mock_run.assert_called_once()


@patch("tools.unlock_wallet.check_network_status")
def test_run_unlock_proceeds_when_online_with_allow_online(mock_status):
    mock_status.return_value = "ONLINE"

    with patch("tools.unlock_wallet.subprocess.run") as mock_run:
        run_unlock("wallet.dat", "candidates.txt", btcrecover_script="fake.py", allow_online=True)
        mock_run.assert_called_once()


def test_find_btcrecover_script_returns_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("tools.unlock_wallet.REPO_ROOT", str(tmp_path))

    assert find_btcrecover_script() is None


@requires_vendor
def test_run_unlock_finds_password_in_public_test_fixture(tmp_path):
    candidates_file = tmp_path / "candidates.txt"
    candidates_file.write_text(f"wrong-guess-1\n{TEST_PASSWORD}\nwrong-guess-2\n")

    result = run_unlock(
        TEST_WALLET,
        str(candidates_file),
        btcrecover_script=VENDOR_SCRIPT,
        allow_online=True,
    )

    assert f"Password found: '{TEST_PASSWORD}'" in result.stdout


@requires_vendor
def test_cli_never_passes_candidates_as_command_line_arguments(tmp_path):
    candidates_file = tmp_path / "candidates.txt"
    candidates_file.write_text(f"wrong-guess-1\n{TEST_PASSWORD}\nwrong-guess-2\n")

    result = subprocess.run(
        [
            sys.executable,
            "tools/unlock_wallet.py",
            TEST_WALLET,
            str(candidates_file),
            "--allow-online",
            "--btcrecover-script",
            VENDOR_SCRIPT,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert TEST_PASSWORD not in result.args
    assert f"Password found: '{TEST_PASSWORD}'" in result.stdout
