import time
from unittest.mock import patch

import pytest

from web.app import create_app


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
