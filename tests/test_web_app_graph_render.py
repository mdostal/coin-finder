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


@patch("web.app.compute_confidence_scores")
def test_findings_page_hides_related_accounts_link_when_nothing_scores(mock_scores, client):
    mock_scores.return_value = []

    resp = client.get("/findings")

    assert resp.status_code == 200
    assert b'href="/findings/related"' not in resp.data


@patch("web.app.compute_confidence_scores")
def test_findings_page_shows_related_accounts_banner_when_candidates_exist(mock_scores, client):
    mock_scores.return_value = [{"address": "1candidate", "score": 10, "confidence_label": "High", "direct_cospend_count": 2, "direct_output_count": 0, "cross_run_count": 1}]

    resp = client.get("/findings")

    assert resp.status_code == 200
    assert b'href="/findings/related"' in resp.data


@patch("web.app.compute_confidence_scores")
def test_findings_related_page_shows_empty_state(mock_scores, client):
    mock_scores.return_value = []

    resp = client.get("/findings/related")

    assert resp.status_code == 200
    assert b"no" in resp.data.lower()


@patch("web.app.compute_confidence_scores")
def test_findings_related_page_shows_scored_candidates_with_breakdown(mock_scores, client):
    mock_scores.return_value = [
        {"address": "1strong", "score": 12, "confidence_label": "High", "direct_cospend_count": 2, "direct_output_count": 1, "cross_run_count": 2},
    ]

    resp = client.get("/findings/related")

    assert resp.status_code == 200
    assert b"1strong" in resp.data
    assert b"High" in resp.data
    assert b"2" in resp.data  # direct_cospend_count appears somewhere in the breakdown
    assert b"candidate" in resp.data.lower()  # explicit non-certainty framing


@patch("web.app.compute_confidence_scores")
def test_findings_related_page_only_scores_bitcoin_findings_as_known(mock_scores, client):
    with patch(
        "web.app.list_findings",
        return_value=[{"coin": "Bitcoin", "address": "1btc", "balance": 0.5, "watched": 0}, {"coin": "Ethereum", "address": "0xabc", "balance": 0.5, "watched": 0}],
    ):
        client.get("/findings/related")

    known_addresses_arg = mock_scores.call_args[0][0]
    assert list(known_addresses_arg) == ["1btc"]


@patch("web.app.compute_confidence_scores")
def test_known_addresses_excludes_zero_balance_crawl_noise(mock_scores, client):
    """
    Regression: _run_crawl_job record_finding()s every discovered address
    regardless of balance -- a zero-balance address a crawl happened to
    touch must not count as "known" (it would make every scored
    candidate instantly "already known" the moment its own discovery
    crawl finishes, exactly the bug caught live during this story).
    """
    with patch(
        "web.app.list_findings",
        return_value=[
            {"coin": "Bitcoin", "address": "1zero", "balance": 0.0, "watched": 0},
            {"coin": "Bitcoin", "address": "1real", "balance": 0.5, "watched": 0},
            {"coin": "Bitcoin", "address": "1watched", "balance": None, "watched": 1},
        ],
    ):
        client.get("/findings/related")

    known_addresses_arg = list(mock_scores.call_args[0][0])
    assert "1zero" not in known_addresses_arg
    assert "1real" in known_addresses_arg
    assert "1watched" in known_addresses_arg
