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
def test_findings_page_links_to_group_view_when_overlaps_exist(mock_overlap, client):
    """
    Superseded by the visual-transaction-graph epic: the link is now a
    proactive banner shown only when there's something to see, not an
    always-present subtle link -- see
    test_web_app_graph_render.py's overlap-banner tests for the
    hides-when-empty counterpart.
    """
    mock_overlap.return_value = {"1shared": {"balance": 2.5, "runs": []}}
    with patch("web.app.list_findings", return_value=[]):
        resp = client.get("/findings")
    assert resp.status_code == 200
    assert b'href="/findings/group-view"' in resp.data


# --- mcrg-02: the multi-select + "View combined graph" entry point --
# before this, mcrg-01's /findings/group-view/graph route only worked if
# you already knew the URL; these confirm the discoverable path from this
# table page actually exists and wires up correctly.


@patch("web.app.find_overlap_addresses")
@patch("web.app.list_crawl_runs")
def test_group_view_page_shows_a_checkbox_for_every_saved_run(mock_runs, mock_overlap, client):
    mock_overlap.return_value = {}
    mock_runs.return_value = [
        {"run_id": 1, "seed_addresses": ["1walletA"], "created_at": 1000.0, "address_count": 5},
        {"run_id": 2, "seed_addresses": ["1walletB"], "created_at": 2000.0, "address_count": 8},
    ]

    resp = client.get("/findings/group-view")

    assert resp.status_code == 200
    assert b'class="run-select-checkbox" value="1"' in resp.data
    assert b'class="run-select-checkbox" value="2"' in resp.data
    assert b"1walletA" in resp.data
    assert b"1walletB" in resp.data


@patch("web.app.find_overlap_addresses")
@patch("web.app.list_crawl_runs")
def test_group_view_page_view_combined_graph_button_starts_disabled(mock_runs, mock_overlap, client):
    """Nothing is checked on page load -- the acceptance criterion that
    fewer than 2 selected runs must not let someone click through to a
    broken/pointless single-run 'combined' view."""
    mock_overlap.return_value = {}
    mock_runs.return_value = [
        {"run_id": 1, "seed_addresses": ["1walletA"], "created_at": 1000.0, "address_count": 5},
        {"run_id": 2, "seed_addresses": ["1walletB"], "created_at": 2000.0, "address_count": 8},
    ]

    resp = client.get("/findings/group-view")

    assert resp.status_code == 200
    assert b'id="view-combined-graph-btn"' in resp.data
    assert b"disabled" in resp.data
    assert b"Select at least 2" in resp.data


@patch("web.app.find_overlap_addresses")
@patch("web.app.list_crawl_runs")
def test_group_view_page_combined_graph_navigation_targets_group_view_graph_route(mock_runs, mock_overlap, client):
    mock_overlap.return_value = {}
    mock_runs.return_value = [
        {"run_id": 1, "seed_addresses": ["1walletA"], "created_at": 1000.0, "address_count": 5},
        {"run_id": 2, "seed_addresses": ["1walletB"], "created_at": 2000.0, "address_count": 8},
    ]

    resp = client.get("/findings/group-view")

    assert resp.status_code == 200
    assert b"/findings/group-view/graph" in resp.data


@patch("web.app.find_overlap_addresses")
@patch("web.app.list_crawl_runs")
def test_group_view_page_with_only_one_saved_run_still_shows_disabled_state(mock_runs, mock_overlap, client):
    mock_overlap.return_value = {}
    mock_runs.return_value = [
        {"run_id": 1, "seed_addresses": ["1walletA"], "created_at": 1000.0, "address_count": 5},
    ]

    resp = client.get("/findings/group-view")

    assert resp.status_code == 200
    assert b'class="run-select-checkbox" value="1"' in resp.data
    assert b"disabled" in resp.data


@patch("web.app.find_overlap_addresses")
@patch("web.app.list_crawl_runs")
def test_group_view_page_with_no_saved_runs_hides_combined_graph_entry_point(mock_runs, mock_overlap, client):
    mock_overlap.return_value = {}
    mock_runs.return_value = []

    resp = client.get("/findings/group-view")

    assert resp.status_code == 200
    assert b"run-select-checkbox" not in resp.data
    assert b'id="view-combined-graph-btn"' not in resp.data
