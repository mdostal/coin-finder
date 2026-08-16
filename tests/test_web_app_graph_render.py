import time
from unittest.mock import patch

import pytest

from web.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _wait_for_done(client, job_id):
    job = None
    for _ in range(100):
        resp = client.get(f"/api/jobs/{job_id}")
        job = resp.get_json()
        if job["status"] != "running":
            break
        time.sleep(0.05)
    return job


@patch("web.app.crawl_wallet_cluster")
def test_crawl_result_page_embeds_graph_data_and_script(mock_crawl, client):
    mock_crawl.return_value = {
        "1seed": {"confidence": "seed", "generation": 0, "discovered_via": None, "balance": 0.5},
        "1cospend": {"confidence": "co-spend", "generation": 1, "discovered_via": "1seed", "balance": None},
    }

    resp = client.post("/item/crawl", data={"addresses": "1seed"}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    _wait_for_done(client, job_id)

    page = client.get(f"/item-result/{job_id}")
    assert page.status_code == 200
    assert b'id="graph-data"' in page.data
    assert b"1cospend" in page.data
    assert b'graph.js' in page.data
    # the existing text report must still be present alongside the graph
    assert b"Transaction Graph Cluster Report" in page.data


@patch("web.app.crawl_wallet_cluster")
def test_crawl_result_page_with_no_discoveries_has_no_graph(mock_crawl, client):
    mock_crawl.return_value = {}

    resp = client.post("/item/crawl", data={"addresses": "1seed"}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    _wait_for_done(client, job_id)

    page = client.get(f"/item-result/{job_id}")
    assert b'id="graph-data"' not in page.data


@patch("web.app.check_fork_coins_for_addresses")
def test_non_crawl_job_result_page_has_no_graph(mock_check, client):
    mock_check.return_value = {"1abc": {"Bitcoin Cash": 0.0}}

    resp = client.post("/item/fork-coins", data={"addresses": "1abc"}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    _wait_for_done(client, job_id)

    page = client.get(f"/item-result/{job_id}")
    assert b'id="graph-data"' not in page.data
    assert b'graph.js' not in page.data


@patch("web.app.find_overlap_addresses")
def test_findings_page_hides_group_view_link_when_nothing_overlaps(mock_overlaps, client):
    mock_overlaps.return_value = {}

    resp = client.get("/findings")

    assert resp.status_code == 200
    assert b'href="/findings/group-view"' not in resp.data


@patch("web.app.find_overlap_addresses")
def test_findings_page_shows_overlap_banner_when_addresses_overlap(mock_overlaps, client):
    mock_overlaps.return_value = {"1shared": {"balance": 2.0, "runs": []}, "1other": {"balance": None, "runs": []}}

    resp = client.get("/findings")

    assert resp.status_code == 200
    assert b'href="/findings/group-view"' in resp.data
    assert b"2" in resp.data
