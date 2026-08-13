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


@patch("web.app.check_addresses_balances")
@patch("web.app.scan_wallet_for_addresses")
def test_scan_wallet_dat_action(mock_scan, mock_check, client, tmp_path):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"not a real wallet")

    mock_scan.return_value = {
        "addresses": [{"address": "1abc", "source": "key"}],
        "encrypted_key_count": 0,
        "unparsed_record_types": {},
    }
    mock_check.return_value = {
        "results": [{"address": "1abc", "source": "key", "balance": 0.0}],
        "limited": False,
        "total_available": 1,
    }

    resp = client.post("/item/scan-wallet-dat", data={"wallet_path": str(wallet_file)}, follow_redirects=False)
    assert resp.status_code == 302
    job = _wait_for_job(client, _job_id_from_redirect(resp))

    assert job["status"] == "done"
    mock_scan.assert_called_once_with(str(wallet_file))
    mock_check.assert_called_once()


@patch("web.app.check_addresses_balances")
@patch("web.app.scan_wallet_for_addresses")
def test_scan_wallet_dat_action_reports_progress(mock_scan, mock_check, client, tmp_path):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"not a real wallet")

    mock_scan.return_value = {
        "addresses": [{"address": "1abc", "source": "key"}],
        "encrypted_key_count": 0,
        "unparsed_record_types": {},
    }

    def fake_check(addresses, progress_callback=None):
        progress_callback(1, 1, "1abc")
        return {"results": [{"address": "1abc", "source": "key", "balance": 0.0}], "limited": False, "total_available": 1}

    mock_check.side_effect = fake_check

    resp = client.post("/item/scan-wallet-dat", data={"wallet_path": str(wallet_file)}, follow_redirects=False)
    job = _wait_for_job(client, _job_id_from_redirect(resp))

    assert job["status"] == "done"
    assert job["progress"] == {"current": 1, "total": 1, "message": "1abc"}


def test_scan_wallet_dat_rejects_missing_file(client, tmp_path):
    resp = client.post("/item/scan-wallet-dat", data={"wallet_path": str(tmp_path / "nope.dat")})
    assert resp.status_code == 400


@patch("web.app.crawl_wallet_cluster")
def test_crawl_action_writes_addresses_to_temp_file_not_raw_param(mock_crawl, client):
    mock_crawl.return_value = {}

    resp = client.post("/item/crawl", data={"addresses": "1abc\n1def\n"}, follow_redirects=False)
    assert resp.status_code == 302
    job = _wait_for_job(client, _job_id_from_redirect(resp))

    assert job["status"] == "done"
    mock_crawl.assert_called_once()
    seed_addresses = mock_crawl.call_args[0][0]
    assert seed_addresses == ["1abc", "1def"]


@patch("web.app.check_fork_coins_for_addresses")
def test_fork_coins_action(mock_check, client):
    mock_check.return_value = {"1abc": {"Bitcoin Cash": 0.0, "Bitcoin Gold": 0.0}}

    resp = client.post("/item/fork-coins", data={"addresses": "1abc"}, follow_redirects=False)
    assert resp.status_code == 302
    job = _wait_for_job(client, _job_id_from_redirect(resp))

    assert job["status"] == "done"
    mock_check.assert_called_once_with(["1abc"])


@patch("web.app.scan_directory")
def test_find_seed_phrases_action_never_includes_phrase_text(mock_scan, client, tmp_path):
    mock_scan.return_value = {
        str(tmp_path / "notes.txt"): [{"phrase": "abandon abandon abandon", "word_count": 12}]
    }

    resp = client.post("/item/find-seed-phrases", data={"target_path": str(tmp_path)}, follow_redirects=False)
    assert resp.status_code == 302
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_job(client, job_id)

    assert job["status"] == "done"
    assert "abandon" not in str(job)

    page = client.get(f"/item-result/{job_id}")
    assert "abandon" not in page.get_data(as_text=True)


def test_find_seed_phrases_rejects_missing_path(client, tmp_path):
    resp = client.post("/item/find-seed-phrases", data={"target_path": str(tmp_path / "nope")})
    assert resp.status_code == 400


@patch("web.app.match_phrases")
@patch("web.app.load_phrases_from_file")
def test_match_seed_phrases_action_only_shows_matched_phrase_text(mock_load, mock_match, client, tmp_path):
    phrases_file = tmp_path / "candidates.txt"
    phrases_file.write_text("phrase one\nphrase two\n")

    mock_load.return_value = ["phrase one", "phrase two"]
    mock_match.return_value = {
        "phrase one": [{"coin": "Bitcoin", "scheme": "bip44", "index": 0, "address": "1abc", "balance": 0.0}],
        "phrase two": [{"coin": "Bitcoin", "scheme": "bip44", "index": 0, "address": "1def", "balance": 1.5}],
    }

    resp = client.post("/item/match-seed-phrases", data={"phrases_file": str(phrases_file)}, follow_redirects=False)
    assert resp.status_code == 302
    job_id = _job_id_from_redirect(resp)
    job = _wait_for_job(client, job_id)

    assert job["status"] == "done"
    assert "phrase two" in job["result"]["report"]
    assert "phrase one" not in job["result"]["report"]


def test_match_seed_phrases_rejects_missing_file(client, tmp_path):
    resp = client.post("/item/match-seed-phrases", data={"phrases_file": str(tmp_path / "nope.txt")})
    assert resp.status_code == 400


def test_item_result_unknown_job_returns_404(client):
    resp = client.get("/item-result/does-not-exist")
    assert resp.status_code == 404
