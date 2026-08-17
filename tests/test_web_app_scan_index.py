from unittest.mock import patch

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@patch("web.app.start_job")
@patch("web.app.create_job")
def test_start_scan_passes_default_index_db_path_when_checkbox_checked(mock_create_job, mock_start_job, client, tmp_path):
    mock_create_job.return_value = "job-1"

    client.post("/scan", data={"input_dir": str(tmp_path), "dedup_index": "1"}, follow_redirects=False)

    call_args = mock_start_job.call_args[0]
    assert call_args[1].__name__ == "_run_find_job"
    assert call_args[4] is not None  # index_db_path


@patch("web.app.start_job")
@patch("web.app.create_job")
def test_start_scan_disables_index_when_checkbox_unchecked(mock_create_job, mock_start_job, client, tmp_path):
    mock_create_job.return_value = "job-1"

    client.post("/scan", data={"input_dir": str(tmp_path)}, follow_redirects=False)

    call_args = mock_start_job.call_args[0]
    assert call_args[4] is None  # index_db_path


@patch("web.app.list_scanned_files")
def test_index_page_shows_dedup_index_count(mock_list, client):
    mock_list.return_value = [{"file_hash": "a", "file_path": "/a", "first_seen_at": 0}]
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"1 file" in resp.data


@patch("web.app.clear_scan_index")
def test_scan_index_clear(mock_clear, client):
    resp = client.post("/scan-index/clear", follow_redirects=False)
    assert resp.status_code == 302
    mock_clear.assert_called_once()
