from unittest.mock import patch

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@patch("web.app.list_findings")
def test_findings_page_loads(mock_list, client):
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.5, "source_path": "/w.dat", "source_label": "scan", "status": "new", "first_seen_at": 0, "last_checked_at": 0}
    ]
    resp = client.get("/findings")
    assert resp.status_code == 200
    mock_list.assert_called_once_with(include_archived=False)


@patch("web.app.list_findings")
def test_findings_page_shows_inconclusive_for_none_balance_not_zero(mock_list, client):
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": None, "source_path": None, "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0}
    ]
    resp = client.get("/findings")
    assert resp.status_code == 200
    assert b"inconclusive" in resp.data
    # Never rendered as a bare "0" or "0.0" standing in for None.
    assert b">0<" not in resp.data
    assert b">0.0<" not in resp.data


@patch("web.app.list_findings")
def test_findings_page_include_archived_query_param(mock_list, client):
    mock_list.return_value = []
    resp = client.get("/findings?include_archived=1")
    assert resp.status_code == 200
    mock_list.assert_called_once_with(include_archived=True)


@patch("web.app.archive")
def test_findings_archive_single_row(mock_archive, client):
    resp = client.post("/findings/archive", data={"coin": "Bitcoin", "address": "1abc"}, follow_redirects=False)
    assert resp.status_code == 302
    mock_archive.assert_called_once_with("Bitcoin", "1abc")


@patch("web.app.unarchive")
def test_findings_unarchive_single_row(mock_unarchive, client):
    resp = client.post("/findings/unarchive", data={"coin": "Bitcoin", "address": "1abc"}, follow_redirects=False)
    assert resp.status_code == 302
    mock_unarchive.assert_called_once_with("Bitcoin", "1abc")


@patch("web.app.archive_all_zero_balance")
def test_findings_archive_all_zero(mock_archive_all, client):
    resp = client.post("/findings/archive-all-zero", follow_redirects=False)
    assert resp.status_code == 302
    mock_archive_all.assert_called_once()
