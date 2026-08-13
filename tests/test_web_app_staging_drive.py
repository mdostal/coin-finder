import re
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from web.app import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _wait_for_terminal(client, job_id, timeout_iterations=100):
    job = None
    for _ in range(timeout_iterations):
        resp = client.get(f"/api/jobs/{job_id}")
        job = resp.get_json()
        if job["status"] != "running":
            break
        time.sleep(0.05)
    return job


def _job_id_from_redirect(resp):
    return resp.headers["Location"].rstrip("/").split("/")[-1]


def test_stage_copies_file_and_leaves_original(client, tmp_path):
    source = tmp_path / "found_wallet.dat"
    source.write_bytes(b"wallet-bytes")
    staging_dir = tmp_path / "staged"

    resp = client.post(
        "/item/stage",
        data={"file_path": str(source), "staging_dir": str(staging_dir)},
    )

    assert resp.status_code == 200
    assert source.exists()  # copy, not move
    staged_file = staging_dir / "found_wallet.dat"
    assert staged_file.exists()
    assert staged_file.read_bytes() == b"wallet-bytes"


def test_stage_refuses_to_overwrite_existing_same_named_file(client, tmp_path):
    source = tmp_path / "found_wallet.dat"
    source.write_bytes(b"new-bytes")
    staging_dir = tmp_path / "staged"
    staging_dir.mkdir()
    (staging_dir / "found_wallet.dat").write_bytes(b"already-here")

    resp = client.post(
        "/item/stage",
        data={"file_path": str(source), "staging_dir": str(staging_dir)},
    )

    assert resp.status_code == 409
    assert (staging_dir / "found_wallet.dat").read_bytes() == b"already-here"


def test_stage_rejects_missing_source_file(client, tmp_path):
    resp = client.post(
        "/item/stage",
        data={"file_path": str(tmp_path / "nope.dat"), "staging_dir": str(tmp_path / "staged")},
    )
    assert resp.status_code == 400


def test_drive_form_loads(client):
    resp = client.get("/drive")
    assert resp.status_code == 200


@patch("web.app.scan_drive_for_wallets")
@patch("web.app.get_drive_service")
def test_drive_scan_wires_to_scan_drive_for_wallets(mock_get_service, mock_scan, client, tmp_path):
    mock_get_service.return_value = "fake-service"
    mock_scan.return_value = [
        {"drive_file_id": "1", "name": "wallet.dat", "local_path": str(tmp_path / "1_wallet.dat")}
    ]

    resp = client.post("/drive/scan", data={"output_dir": str(tmp_path)}, follow_redirects=False)
    assert resp.status_code == 302
    job = _wait_for_terminal(client, _job_id_from_redirect(resp))

    assert job["status"] == "done"
    mock_scan.assert_called_once()
    args, kwargs = mock_scan.call_args
    assert args[0] == "fake-service"
    assert args[1] == str(tmp_path)


def test_browse_endpoint_does_not_recurse_into_symlinks(client, tmp_path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    loop_link = real_dir / "loop"
    loop_link.symlink_to(real_dir)

    resp = client.get("/api/browse", query_string={"path": str(real_dir)})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["subdirectories"] == []


def test_browse_endpoint_handles_dotdot_path_without_crashing(client, tmp_path):
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)

    resp = client.get("/api/browse", query_string={"path": str(sub / ".." / "..")})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["path"] == str(tmp_path)


def test_no_route_reads_secret_shaped_values_from_query_string():
    """
    Regression guard: candidate passwords/phrases must only ever be read
    from a POST body (request.form), never a GET query string
    (request.args) -- a URL is far more likely to end up in browser
    history/logs than a form POST body.
    """
    source = (REPO_ROOT / "web" / "app.py").read_text()
    suspicious = re.findall(r'request\.args\.get\(\s*["\'](password|candidate|candidates|phrase|phrases|secret)["\']', source)
    assert suspicious == []
