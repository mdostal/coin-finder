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
def test_item_crawl_default_generations_matches_current_behavior(mock_crawl, client):
    mock_crawl.return_value = {}

    resp = client.post("/item/crawl", data={"addresses": "1abc"}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    job = _wait_for_done(client, job_id)
    assert job["status"] == "done"

    assert mock_crawl.call_args.kwargs["max_generations"] == 2


@patch("web.app.crawl_wallet_cluster")
def test_item_crawl_passes_through_a_valid_generations_value(mock_crawl, client):
    mock_crawl.return_value = {}

    resp = client.post("/item/crawl", data={"addresses": "1abc", "generations": "4"}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    _wait_for_done(client, job_id)

    assert mock_crawl.call_args.kwargs["max_generations"] == 4


@patch("web.app.crawl_wallet_cluster")
def test_item_crawl_clamps_generations_above_the_cap(mock_crawl, client):
    mock_crawl.return_value = {}

    resp = client.post("/item/crawl", data={"addresses": "1abc", "generations": "999"}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    _wait_for_done(client, job_id)

    assert mock_crawl.call_args.kwargs["max_generations"] == 5


@patch("web.app.crawl_wallet_cluster")
def test_item_crawl_clamps_generations_below_the_floor(mock_crawl, client):
    mock_crawl.return_value = {}

    resp = client.post("/item/crawl", data={"addresses": "1abc", "generations": "0"}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    _wait_for_done(client, job_id)

    assert mock_crawl.call_args.kwargs["max_generations"] == 1


@patch("web.app.crawl_wallet_cluster")
def test_item_crawl_falls_back_to_default_on_unparseable_generations(mock_crawl, client):
    mock_crawl.return_value = {}

    resp = client.post("/item/crawl", data={"addresses": "1abc", "generations": "not-a-number"}, follow_redirects=False)
    job_id = resp.headers["Location"].rstrip("/").split("/")[-1]
    _wait_for_done(client, job_id)

    assert mock_crawl.call_args.kwargs["max_generations"] == 2
