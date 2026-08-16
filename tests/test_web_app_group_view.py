from unittest.mock import patch

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@patch("web.app.find_overlap_addresses")
def test_group_view_page_loads(mock_overlap, client):
    mock_overlap.return_value = {}
    resp = client.get("/findings/group-view")
    assert resp.status_code == 200


@patch("web.app.find_overlap_addresses")
def test_group_view_page_shows_empty_state_with_no_overlaps(mock_overlap, client):
    mock_overlap.return_value = {}
    resp = client.get("/findings/group-view")
    assert resp.status_code == 200
    assert b"No overlaps yet" in resp.data


@patch("web.app.find_overlap_addresses")
def test_group_view_page_renders_overlap_addresses(mock_overlap, client):
    mock_overlap.return_value = {
        "1shared": {
            "balance": 2.5,
            "runs": [
                {"run_id": 1, "seed_addresses": ["1walletA"], "confidence": "co-spend", "generation": 1},
                {"run_id": 2, "seed_addresses": ["1walletB"], "confidence": "output", "generation": 2},
            ],
        }
    }
    resp = client.get("/findings/group-view")
    assert resp.status_code == 200
    assert b"1shared" in resp.data
    assert b"1walletA" in resp.data
    assert b"1walletB" in resp.data
    assert b"No overlaps yet" not in resp.data


@patch("web.app.clear_all_crawl_runs")
def test_group_view_clear(mock_clear, client):
    resp = client.post("/findings/group-view/clear", follow_redirects=False)
    assert resp.status_code == 302
    mock_clear.assert_called_once()


@patch("web.app.find_overlap_addresses")
def test_findings_page_links_to_group_view(mock_overlap, client):
    with patch("web.app.list_findings", return_value=[]):
        resp = client.get("/findings")
    assert resp.status_code == 200
    assert b'href="/findings/group-view"' in resp.data
