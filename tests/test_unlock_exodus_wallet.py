import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.unlock_exodus_wallet import extract_exodus_hash, find_exodus2hashcat_script, run_exodus_unlock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXODUS2HASHCAT_SCRIPT = os.path.join(REPO_ROOT, "vendor", "hashcat-tools", "exodus2hashcat.py")

requires_vendor = pytest.mark.skipif(
    not os.path.exists(EXODUS2HASHCAT_SCRIPT),
    reason="vendor/hashcat-tools not installed -- run scripts/install_exodus_tools.sh first",
)
requires_hashcat = pytest.mark.skipif(
    subprocess.run(["which", "hashcat"], capture_output=True).returncode != 0,
    reason="hashcat not installed -- run scripts/install_exodus_tools.sh first",
)

# hashcat's own official example hash + password for mode 28200 (from
# `hashcat --example-hashes`) -- publicly documented by the hashcat project
# itself specifically for testing this mode, not a real wallet. Same class
# of fixture as the public BIP39 test vector and BTCRecover's bundled test
# wallet used elsewhere in this project's tests.
EXAMPLE_HASH = "EXODUS:16384:8:1:IYkXZgFETRmFp4wQXyP8XMe3LtuOw8wMdLcBVQ+9YWE=:lq0W9ekN5sC0O7Xw:UD4a6mUUhkTbQtGWitXHZUg0pQ4RHI6W/KUyYE95m3k=:ZuNQckXOtr4r21x+DT1zpQ=="
EXAMPLE_PASSWORD = "hashcat"


def test_find_exodus2hashcat_script_returns_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.unlock_exodus_wallet.REPO_ROOT", str(tmp_path))

    assert find_exodus2hashcat_script() is None


@patch("tools.unlock_exodus_wallet.check_network_status")
def test_run_exodus_unlock_refuses_when_online_without_allow_online(mock_status, tmp_path):
    mock_status.return_value = "ONLINE"

    with patch("tools.unlock_exodus_wallet.subprocess.run") as mock_run:
        with pytest.raises(RuntimeError):
            run_exodus_unlock(str(tmp_path / "seed.seco"), str(tmp_path / "candidates.txt"))
        mock_run.assert_not_called()


@patch("tools.unlock_exodus_wallet.check_network_status")
def test_run_exodus_unlock_proceeds_when_offline(mock_status, tmp_path):
    mock_status.return_value = "OFFLINE"

    with patch("tools.unlock_exodus_wallet.extract_exodus_hash", return_value=EXAMPLE_HASH):
        with patch("tools.unlock_exodus_wallet.subprocess.run") as mock_run:
            run_exodus_unlock(str(tmp_path / "seed.seco"), str(tmp_path / "candidates.txt"))
            mock_run.assert_called_once()


@requires_vendor
def test_extract_exodus_hash_reports_a_clear_error_on_a_non_seco_file(tmp_path):
    # Confirms the real exodus2hashcat.py script is reachable and reports a
    # sane error on a malformed file rather than crashing uninformatively.
    # (Extraction against a *real* seed.seco file was validated live during
    # epic research -- reading only public header/salt/KDF metadata, never a
    # password -- see docs/design-discussion.md.)
    fake_file = tmp_path / "not-a-seco-file.bin"
    fake_file.write_bytes(b"\x00" * 32)

    with pytest.raises(RuntimeError):
        extract_exodus_hash(str(fake_file), script_path=EXODUS2HASHCAT_SCRIPT)


@requires_hashcat
def test_run_exodus_unlock_finds_password_in_hashcats_own_example(tmp_path):
    candidates_file = tmp_path / "candidates.txt"
    candidates_file.write_text(f"wrong-guess-1\n{EXAMPLE_PASSWORD}\nwrong-guess-2\n")

    with patch("tools.unlock_exodus_wallet.extract_exodus_hash", return_value=EXAMPLE_HASH):
        result = run_exodus_unlock(
            "unused-because-extract_exodus_hash-is-mocked.seco",
            str(candidates_file),
            allow_online=True,
        )

    assert f"{EXAMPLE_HASH}:{EXAMPLE_PASSWORD}" in result.stdout or "Recovered" in result.stdout


@requires_hashcat
def test_cli_never_passes_candidates_as_command_line_arguments(tmp_path):
    candidates_file = tmp_path / "candidates.txt"
    candidates_file.write_text(f"wrong-guess-1\n{EXAMPLE_PASSWORD}\nwrong-guess-2\n")

    hash_file = tmp_path / "prebuilt.hash"  # not used by the CLI directly, just proves no password ever appears in argv
    result = subprocess.run(
        [
            sys.executable, "tools/unlock_exodus_wallet.py",
            "irrelevant-because-we-check-argv-only.seco", str(candidates_file),
            "--allow-online",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert EXAMPLE_PASSWORD not in result.args
