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
    # Called twice: once for the display list (respecting the
    # include_archived query param), once internally for the
    # confidence-scoring known-address set (always wants every known
    # address, archived or not -- an archived finding is still known).
    mock_list.assert_any_call(include_archived=False)


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
    mock_list.assert_any_call(include_archived=True)


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


@patch("web.app.list_findings")
def test_findings_page_offers_graph_and_fork_check_for_bitcoin(mock_list, client):
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.5, "source_path": None, "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0}
    ]
    resp = client.get("/findings")
    assert resp.status_code == 200
    assert b'action="/item/crawl"' in resp.data
    assert b'action="/item/fork-coins"' in resp.data
    assert b'value="1abc"' in resp.data


@patch("web.app.list_findings")
def test_findings_page_hides_bitcoin_only_actions_for_other_coins(mock_list, client):
    mock_list.return_value = [
        {"coin": "Ethereum", "address": "0xabc", "balance": 0.5, "source_path": None, "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0}
    ]
    resp = client.get("/findings")
    assert resp.status_code == 200
    assert b'action="/item/crawl"' not in resp.data
    assert b'action="/item/fork-coins"' not in resp.data


@patch("web.app.list_findings")
def test_findings_page_highlights_watched_rows(mock_list, client):
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.5, "source_path": None, "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0, "watched": 1, "watch_note": "suspected mining chain"}
    ]
    resp = client.get("/findings")
    assert resp.status_code == 200
    assert b"watched-row" in resp.data
    assert b"suspected mining chain" in resp.data
    assert b'action="/findings/unwatch"' in resp.data


@patch("web.app.set_watched")
def test_findings_watch_stores_the_note(mock_set_watched, client):
    resp = client.post("/findings/watch", data={"coin": "Bitcoin", "address": "1abc", "note": "mining chain"}, follow_redirects=False)
    assert resp.status_code == 302
    mock_set_watched.assert_called_once_with("Bitcoin", "1abc", True, note="mining chain")


@patch("web.app.set_watched")
def test_findings_unwatch(mock_set_watched, client):
    resp = client.post("/findings/unwatch", data={"coin": "Bitcoin", "address": "1abc"}, follow_redirects=False)
    assert resp.status_code == 302
    mock_set_watched.assert_called_once_with("Bitcoin", "1abc", False)


@patch("web.app.clear_all_findings")
def test_findings_clear_all(mock_clear_all, client):
    resp = client.post("/findings/clear-all", follow_redirects=False)
    assert resp.status_code == 302
    mock_clear_all.assert_called_once()


@patch("web.app.list_findings")
def test_findings_page_shows_a_real_coin_icon_for_known_coins(mock_list, client):
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.5, "source_path": None, "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0}
    ]
    resp = client.get("/findings")
    assert resp.status_code == 200
    assert b"coin-icons/btc.svg" in resp.data


@patch("web.app.list_findings")
def test_findings_page_falls_back_to_initials_badge_for_a_coin_with_no_icon_asset(mock_list, client):
    mock_list.return_value = [
        {"coin": "Diamond Coin", "address": "1abc", "balance": 0.5, "source_path": None, "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0}
    ]
    resp = client.get("/findings")
    assert resp.status_code == 200
    assert b"coin-icons/" not in resp.data
    assert b"DMD" in resp.data


@patch("web.app.list_findings")
def test_findings_page_truncates_a_long_source_path_but_keeps_the_full_value_for_copy_and_hover(mock_list, client):
    long_path = "/Volumes/OldDrive/nested/three/computers/deep/backup-folder/another-backup/wallet-files/2015/backup_wallet.dat"
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.5, "source_path": long_path, "source_label": "scan", "status": "new", "first_seen_at": 0, "last_checked_at": 0}
    ]
    resp = client.get("/findings")
    assert resp.status_code == 200
    assert b"backup_wallet.dat" in resp.data  # the useful, end-of-path part is visible
    assert f'data-path="{long_path}"'.encode() in resp.data  # full path preserved for Copy
    assert f'title="{long_path}"'.encode() in resp.data  # full path preserved for hover
    # the truncated display text starts with an ellipsis, not the real start of the path
    assert "…ther-backup/wallet-files/2015/backup_wallet.dat".encode() in resp.data
