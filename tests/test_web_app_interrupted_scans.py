import json
from unittest.mock import patch

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _write_checkpoint(output_root, scan_name, start_path, completed_dirs, potential_wallets):
    checks_dir = output_root / scan_name / "checks"
    checks_dir.mkdir(parents=True)
    (checks_dir / "scan_checkpoint.json").write_text(
        json.dumps(
            {
                "start_path": str(start_path),
                "completed_dirs": completed_dirs,
                "potential_wallets": potential_wallets,
            }
        )
    )


def test_index_shows_interrupted_scan_with_resume_action(client, tmp_path):
    input_dir = tmp_path / "old-drive"
    input_dir.mkdir()
    output_root = tmp_path / "ui_output"
    _write_checkpoint(output_root, "old-drive", input_dir, ["/a", "/b"], ["/a/wallet.dat"])

    with patch("web.app.DEFAULT_OUTPUT_ROOT", output_root):
        resp = client.get("/")

    assert resp.status_code == 200
    assert str(input_dir).encode() in resp.data
    assert b"2 directories" in resp.data or b"2 director" in resp.data
    assert f'value="{input_dir}"'.encode() in resp.data


def test_index_hides_checkpoint_whose_start_path_no_longer_exists(client, tmp_path):
    output_root = tmp_path / "ui_output"
    _write_checkpoint(output_root, "gone", "/no/longer/mounted", [], [])

    with patch("web.app.DEFAULT_OUTPUT_ROOT", output_root):
        resp = client.get("/")

    assert resp.status_code == 200
    assert b"interrupted scan" not in resp.data.lower()


def test_index_shows_no_banner_when_no_checkpoints_exist(client, tmp_path):
    output_root = tmp_path / "ui_output"
    output_root.mkdir()

    with patch("web.app.DEFAULT_OUTPUT_ROOT", output_root):
        resp = client.get("/")

    assert resp.status_code == 200
    assert b"interrupted scan" not in resp.data.lower()


def _write_balance_checkpoint(output_root, scan_name, results):
    checks_dir = output_root / scan_name / "checks"
    checks_dir.mkdir(parents=True)
    (checks_dir / "balance_checkpoint.json").write_text(
        json.dumps({"input_file": str(checks_dir / "wallet_analysis.json"), "results": results})
    )


def test_index_shows_interrupted_balance_check_with_resume_action(client, tmp_path):
    output_root = tmp_path / "ui_output"
    _write_balance_checkpoint(
        output_root,
        "old-drive",
        {"walletA.dat": {"Bitcoin": {"1abc": 0.5, "1def": None}}},
    )

    with patch("web.app.DEFAULT_OUTPUT_ROOT", output_root):
        resp = client.get("/")

    assert resp.status_code == 200
    assert b"interrupted balance check" in resp.data.lower()
    assert str(output_root / "old-drive").encode() in resp.data
    assert b"1 address" in resp.data  # only the confirmed one counts


def test_index_shows_no_balance_banner_when_no_balance_checkpoints_exist(client, tmp_path):
    output_root = tmp_path / "ui_output"
    output_root.mkdir()

    with patch("web.app.DEFAULT_OUTPUT_ROOT", output_root):
        resp = client.get("/")

    assert resp.status_code == 200
    assert b"interrupted balance check" not in resp.data.lower()
