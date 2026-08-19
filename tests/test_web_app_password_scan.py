import time
from pathlib import Path
from unittest.mock import patch

import pytest

from web.app import create_app
from web.vault import list_vault_entries


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _wait_for_job(client, job_id, timeout_iterations=100):
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


def test_find_password_candidates_action_scans_a_real_directory_and_redirects_to_review(client, tmp_path):
    (tmp_path / "notes.txt").write_text("password: hunter2live")

    resp = client.post("/item/find-password-candidates", data={"target_path": str(tmp_path)}, follow_redirects=False)
    assert resp.status_code == 302
    assert "/password-scan/" in resp.headers["Location"]

    job_id = _job_id_from_redirect(resp)
    job = _wait_for_job(client, job_id)

    assert job["status"] == "done"
    assert job["result"]["counts"] == {str(tmp_path / "notes.txt"): 1}


def test_find_password_candidates_rejects_missing_path(client, tmp_path):
    resp = client.post("/item/find-password-candidates", data={"target_path": str(tmp_path / "nope")})
    assert resp.status_code == 400


def test_password_scan_review_unknown_job_returns_404(client):
    resp = client.get("/password-scan/does-not-exist")
    assert resp.status_code == 404


def test_password_scan_review_page_shows_file_line_and_matched_value(client, tmp_path):
    (tmp_path / "notes.txt").write_text("password: hunter2live")

    resp = client.post("/item/find-password-candidates", data={"target_path": str(tmp_path)}, follow_redirects=False)
    job_id = _job_id_from_redirect(resp)
    _wait_for_job(client, job_id)

    page = client.get(f"/password-scan/{job_id}")
    body = page.get_data(as_text=True)

    assert page.status_code == 200
    assert str(tmp_path / "notes.txt") in body
    assert "hunter2live" in body  # matched value present (masked client-side via secret-reveal.js, not server-side)
    assert "label" in body
    assert "best-effort heuristic" in body.lower()


def test_password_scan_review_reports_zero_candidates_for_ordinary_prose(client, tmp_path):
    (tmp_path / "notes.txt").write_text("The quick brown fox jumps over the lazy dog near the riverbank.")

    resp = client.post("/item/find-password-candidates", data={"target_path": str(tmp_path)}, follow_redirects=False)
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_job(client, job_id)

    assert job["status"] == "done"
    assert job["result"]["counts"] == {}

    page = client.get(f"/password-scan/{job_id}")
    assert "No candidates found." in page.get_data(as_text=True)


@patch("web.app.add_vault_entry")
@patch("web.app.record_finding")
def test_find_password_candidates_never_writes_to_findings_or_vault(mock_record_finding, mock_add_vault_entry, client, tmp_path):
    # Real credential-labeled AND coin-proximity candidates, so both
    # matching paths run -- neither should ever touch findings.db or the
    # vault. This scanner's output is candidates only (pns-01); vault
    # ingestion is a separate, not-yet-built follow-up story (pns-02).
    (tmp_path / "notes.txt").write_text("password: hunter2live\nbitcoin backup: correcthorsebatterystaple\n")

    resp = client.post("/item/find-password-candidates", data={"target_path": str(tmp_path)}, follow_redirects=False)
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_job(client, job_id)

    assert job["status"] == "done"
    assert sum(job["result"]["counts"].values()) >= 2

    client.get(f"/password-scan/{job_id}")

    mock_record_finding.assert_not_called()
    mock_add_vault_entry.assert_not_called()


# --- pns-02: confirm-and-ingest reviewed candidates into the vault ---------


def _scan_and_get_job(client, tmp_path):
    resp = client.post("/item/find-password-candidates", data={"target_path": str(tmp_path)}, follow_redirects=False)
    job_id = _job_id_from_redirect(resp)
    _wait_for_job(client, job_id)
    return job_id


@patch("web.app.add_vault_entry")
def test_password_scan_confirm_adds_only_selected_candidates_not_all_discovered(mock_add, client, tmp_path):
    # Two label-type candidates on two separate lines of one file -- order
    # within a single file's candidate list is deterministic (find_candidate_lines
    # walks lines top to bottom), so index 0 is always "first-password" and
    # index 1 is always "second-password" regardless of os.walk ordering.
    (tmp_path / "notes.txt").write_text("password: first-password\npassword: second-password\n")
    job_id = _scan_and_get_job(client, tmp_path)

    captured = {}

    def _capture(name, value_file_path, description="", sm_name=None):
        with open(value_file_path) as f:
            captured["value"] = f.read()

    mock_add.side_effect = _capture

    resp = client.post(f"/password-scan/{job_id}/confirm", data={"candidate": "0"}, follow_redirects=False)

    assert resp.status_code == 200
    mock_add.assert_called_once()
    assert captured["value"] == "first-password"


@patch("web.app.add_vault_entry")
def test_password_scan_confirm_writes_value_to_temp_file_then_cleans_it_up(mock_add, client, tmp_path):
    (tmp_path / "notes.txt").write_text("password: hunter2live\n")
    job_id = _scan_and_get_job(client, tmp_path)

    captured = {}

    def _capture(name, value_file_path, description="", sm_name=None):
        captured["path"] = value_file_path
        assert Path(value_file_path).exists(), "value file must exist while add_vault_entry runs"
        with open(value_file_path) as f:
            assert f.read() == "hunter2live"

    mock_add.side_effect = _capture

    resp = client.post(f"/password-scan/{job_id}/confirm", data={"candidate": "0"}, follow_redirects=False)

    assert resp.status_code == 200
    assert "path" in captured
    assert not Path(captured["path"]).exists(), "temp value file must be deleted after add_vault_entry returns"


@patch("web.app.add_vault_entry")
def test_password_scan_confirm_empty_selection_is_not_a_silent_no_op(mock_add, client, tmp_path):
    (tmp_path / "notes.txt").write_text("password: hunter2live\n")
    job_id = _scan_and_get_job(client, tmp_path)

    resp = client.post(f"/password-scan/{job_id}/confirm", data={}, follow_redirects=False)

    assert resp.status_code == 400
    assert b"select" in resp.data.lower()
    mock_add.assert_not_called()


def test_password_scan_confirm_unknown_job_returns_404(client):
    resp = client.post("/password-scan/does-not-exist/confirm", data={"candidate": "0"})
    assert resp.status_code == 404


@patch("web.vault.shutil.which", return_value=None)
def test_password_scan_confirm_reconfirming_same_candidate_creates_no_duplicate(mock_which, client, tmp_path, monkeypatch):
    monkeypatch.setattr("web.vault.FALLBACK_ENV_PATH", tmp_path / "vault_fallback.env")
    monkeypatch.setattr("web.vault.FALLBACK_META_PATH", tmp_path / "vault_fallback_meta.json")

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "notes.txt").write_text("password: hunter2live\n")

    job_id_1 = _scan_and_get_job(client, source_dir)
    resp1 = client.post(f"/password-scan/{job_id_1}/confirm", data={"candidate": "0"}, follow_redirects=False)
    assert resp1.status_code == 200

    # Re-scan the exact same, unchanged file -- a fresh job_id, but the same
    # underlying candidate (same file path, line, match type, value).
    job_id_2 = _scan_and_get_job(client, source_dir)
    resp2 = client.post(f"/password-scan/{job_id_2}/confirm", data={"candidate": "0"}, follow_redirects=False)
    assert resp2.status_code == 200

    entries = list_vault_entries()
    assert len(entries) == 1
    assert entries[0]["name"].startswith("note-scan-")


@patch("web.vault.shutil.which", return_value=None)
def test_password_scan_confirm_distinct_sources_get_distinct_names(mock_which, client, tmp_path, monkeypatch):
    monkeypatch.setattr("web.vault.FALLBACK_ENV_PATH", tmp_path / "vault_fallback.env")
    monkeypatch.setattr("web.vault.FALLBACK_META_PATH", tmp_path / "vault_fallback_meta.json")

    dir_a = tmp_path / "a"
    dir_a.mkdir()
    (dir_a / "notes.txt").write_text("password: aaaaaaaa\n")
    dir_b = tmp_path / "b"
    dir_b.mkdir()
    (dir_b / "notes.txt").write_text("password: bbbbbbbb\n")

    job_id_a = _scan_and_get_job(client, dir_a)
    client.post(f"/password-scan/{job_id_a}/confirm", data={"candidate": "0"}, follow_redirects=False)

    job_id_b = _scan_and_get_job(client, dir_b)
    client.post(f"/password-scan/{job_id_b}/confirm", data={"candidate": "0"}, follow_redirects=False)

    entries = list_vault_entries()
    assert len(entries) == 2
    names = {e["name"] for e in entries}
    assert len(names) == 2


def test_password_scan_review_page_has_disabled_confirm_button_and_checkboxes(client, tmp_path):
    (tmp_path / "notes.txt").write_text("password: hunter2live\n")
    job_id = _scan_and_get_job(client, tmp_path)

    page = client.get(f"/password-scan/{job_id}")
    body = page.get_data(as_text=True)

    assert 'name="candidate"' in body
    assert "disabled" in body
