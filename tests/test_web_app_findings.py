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
def test_findings_page_offers_bulk_watch_and_try_unlock_for_any_coin(mock_list, client):
    """
    Watch selected / Try unlock selected are NOT Bitcoin-only tools (unlike
    Graph/Check fork coins) -- they must appear even for a page of
    non-Bitcoin findings, and the per-row checkbox must be selectable on
    every coin's row, not just Bitcoin's.
    """
    mock_list.return_value = [
        {"coin": "Ethereum", "address": "0xabc", "balance": 0.5, "source_path": None, "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0}
    ]
    resp = client.get("/findings")
    assert resp.status_code == 200
    assert b'formaction="/findings/watch-bulk"' in resp.data
    assert b'id="bulk-try-unlock"' in resp.data
    assert b'value="0xabc"' in resp.data
    # Bitcoin-only actions still absent for an all-Ethereum page.
    assert b'action="/item/crawl"' not in resp.data
    assert b'action="/item/fork-coins"' not in resp.data


@patch("web.app.set_watched")
def test_findings_watch_bulk_applies_one_note_to_every_checked_address_across_coins(mock_set_watched, client):
    resp = client.post(
        "/findings/watch-bulk",
        data={"selection": "Bitcoin\t1abc\nEthereum\t0xdef", "note": "suspected mining chain"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert mock_set_watched.call_count == 2
    mock_set_watched.assert_any_call("Bitcoin", "1abc", True, note="suspected mining chain")
    mock_set_watched.assert_any_call("Ethereum", "0xdef", True, note="suspected mining chain")


@patch("web.app.set_watched")
def test_findings_watch_bulk_note_is_optional(mock_set_watched, client):
    resp = client.post("/findings/watch-bulk", data={"selection": "Bitcoin\t1abc"}, follow_redirects=False)
    assert resp.status_code == 302
    mock_set_watched.assert_called_once_with("Bitcoin", "1abc", True, note="")


@patch("web.app.set_watched")
def test_findings_watch_bulk_requires_at_least_one_selection(mock_set_watched, client):
    resp = client.post("/findings/watch-bulk", data={"note": "no selection made"}, follow_redirects=False)
    assert resp.status_code == 302
    mock_set_watched.assert_not_called()


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
def test_findings_page_shows_full_path_as_a_collapsed_tree_with_connectors_and_bold_filename(mock_list, client):
    long_path = "/Volumes/OldDrive/nested/three/computers/deep/backup-folder/another-backup/wallet-files/2015/backup_wallet.dat"
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.5, "source_path": long_path, "source_label": "scan", "status": "new", "first_seen_at": 0, "last_checked_at": 0}
    ]
    resp = client.get("/findings")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # Full path still reachable via Copy even while the tree is collapsed --
    # the Copy button/title live outside the <details> hidden region.
    assert f'data-path="{long_path}"' in body
    assert f'title="{long_path}"' in body
    # Chain-of-custody disclosure is collapsed by default (no `open` attribute).
    assert "Chain of custody" in body
    assert '<details class="custody-disclosure">' in body
    assert '<details class="custody-disclosure" open' not in body
    # Full path rendered as an indented tree, one segment per line, `└─`
    # connectors, filename bolded at the end.
    assert "└─" in body
    assert '<strong class="path-tree-file">backup_wallet.dat</strong>' in body
    assert ">OldDrive<" in body
    assert ">backup-folder<" in body


@patch("web.app.list_findings")
def test_findings_page_shows_logged_source_metadata_line(mock_list, client):
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.5, "source_path": "/w.dat", "source_label": "scan_wallet_dat", "status": "new", "first_seen_at": 0, "last_checked_at": 0}
    ]
    resp = client.get("/findings")
    assert resp.status_code == 200
    assert b"LOGGED" in resp.data
    assert b"SOURCE scan_wallet_dat" in resp.data


@patch("web.app.list_findings")
def test_findings_page_metadata_line_falls_back_to_scan_label(mock_list, client):
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.5, "source_path": "/w.dat", "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0}
    ]
    resp = client.get("/findings")
    assert resp.status_code == 200
    assert b"SOURCE scan" in resp.data


@patch("web.app.list_findings")
def test_findings_page_has_a_coin_filter_tab_per_distinct_coin(mock_list, client):
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0, "source_path": None, "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0},
        {"coin": "Litecoin", "address": "Labc", "balance": 0, "source_path": None, "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0},
    ]
    resp = client.get("/findings")
    assert resp.status_code == 200
    assert b'data-coin-filter="all"' in resp.data
    assert b'data-coin-filter="Bitcoin"' in resp.data
    assert b'data-coin-filter="Litecoin"' in resp.data


@patch("web.app.list_findings")
def test_findings_page_has_a_live_search_field(mock_list, client):
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0, "source_path": None, "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0}
    ]
    resp = client.get("/findings")
    assert resp.status_code == 200
    assert b'id="findings-search"' in resp.data
    # Each card carries the searchable haystack the client-side JS filters against.
    assert b'data-search="bitcoin 1abc' in resp.data.lower()


@patch("web.app.list_findings")
def test_findings_page_shows_confirmed_find_wax_seal_for_nonzero_balance_only(mock_list, client):
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.5, "source_path": None, "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0},
        {"coin": "Litecoin", "address": "Labc", "balance": 0, "source_path": None, "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0},
    ]
    resp = client.get("/findings")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "CONFIRMED FIND" in body
    assert body.count("wax-seal") == 1  # only the non-zero-balance row gets one


@patch("web.app.list_findings")
def test_findings_page_vertical_coin_tab_uses_real_icon_and_coin_name(mock_list, client):
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.5, "source_path": None, "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0}
    ]
    resp = client.get("/findings")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "finding-card-tab" in body
    assert "coin-icons/btc.svg" in body
    assert ">Bitcoin<" in body


# --- ccu-02: per-finding unlock-status badge + persistent batch-result banner ---


@patch("web.app.list_auto_unlock_history", return_value=[])
@patch("web.app.latest_status_by_wallet_path")
@patch("web.app.list_findings")
def test_findings_page_badge_shows_unlocked_for_matched_history_row(mock_list, mock_latest, mock_history, client):
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.0, "source_path": "/w.dat", "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0, "watched": 0, "watch_note": ""}
    ]
    mock_latest.return_value = {"/w.dat": {"matched": True, "vault_label": "password-1", "run_at": 100.0}}

    resp = client.get("/findings")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "unlocked" in body
    assert "tried, no match" not in body
    assert "not yet tried" not in body
    # Badge copy must say "wallet," never "address" -- auto_unlock_history
    # is wallet_path-scoped, not per-address.
    assert "unlock-badge" in body
    assert "address" not in body.lower().split("unlock-badge", 1)[1].split("</span>", 1)[0]


@patch("web.app.list_auto_unlock_history", return_value=[])
@patch("web.app.latest_status_by_wallet_path")
@patch("web.app.list_findings")
def test_findings_page_badge_shows_tried_no_match_for_unmatched_history_row(mock_list, mock_latest, mock_history, client):
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.0, "source_path": "/w.dat", "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0, "watched": 0, "watch_note": ""}
    ]
    mock_latest.return_value = {"/w.dat": {"matched": False, "vault_label": None, "run_at": 100.0}}

    resp = client.get("/findings")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "tried, no match" in body
    assert ">unlocked<" not in body


@patch("web.app.list_auto_unlock_history", return_value=[])
@patch("web.app.latest_status_by_wallet_path")
@patch("web.app.list_findings")
def test_findings_page_badge_shows_not_yet_tried_for_no_history_row(mock_list, mock_latest, mock_history, client):
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.0, "source_path": "/w.dat", "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0, "watched": 0, "watch_note": ""}
    ]
    mock_latest.return_value = {}

    resp = client.get("/findings")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "not yet tried" in body


@patch("web.app.list_auto_unlock_history", return_value=[])
@patch("web.app.latest_status_by_wallet_path", return_value={})
@patch("web.app.list_findings")
def test_findings_page_no_unlock_badge_for_finding_without_source_path(mock_list, mock_latest, mock_history, client):
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.0, "source_path": None, "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0, "watched": 0, "watch_note": ""}
    ]

    resp = client.get("/findings")

    assert resp.status_code == 200
    assert b"unlock-badge" not in resp.data


@patch("web.app.list_auto_unlock_history")
@patch("web.app.latest_status_by_wallet_path", return_value={})
@patch("web.app.list_findings", return_value=[])
def test_findings_page_batch_summary_banner_shows_last_run_counts(mock_list, mock_latest, mock_history, client):
    mock_history.return_value = [
        {
            "run_id": "run-2",
            "run_at": 200.0,
            "wallets": [
                {"wallet_path": "/a.dat", "vault_label": "password-1", "matched": True},
                {"wallet_path": "/b.dat", "vault_label": None, "matched": False},
                {"wallet_path": "/c.dat", "vault_label": None, "matched": False},
            ],
        },
        {
            "run_id": "run-1",
            "run_at": 100.0,
            "wallets": [{"wallet_path": "/a.dat", "vault_label": None, "matched": False}],
        },
    ]

    resp = client.get("/findings")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Last batch" in body
    assert "1 unlocked" in body
    assert "2 no match" in body
    # Reflects the newest run's counts, not the older one's.
    assert "0 unlocked" not in body


@patch("web.app.list_auto_unlock_history")
@patch("web.app.latest_status_by_wallet_path", return_value={})
@patch("web.app.list_findings", return_value=[])
def test_findings_page_batch_summary_banner_links_to_history_page(mock_list, mock_latest, mock_history, client):
    mock_history.return_value = [
        {"run_id": "run-1", "run_at": 100.0, "wallets": [{"wallet_path": "/a.dat", "vault_label": "password-1", "matched": True}]}
    ]

    resp = client.get("/findings")

    assert resp.status_code == 200
    assert b'href="/auto-unlock/history"' in resp.data


@patch("web.app.list_auto_unlock_history", return_value=[])
@patch("web.app.latest_status_by_wallet_path", return_value={})
@patch("web.app.list_findings", return_value=[])
def test_findings_page_no_batch_summary_banner_when_no_history(mock_list, mock_latest, mock_history, client):
    resp = client.get("/findings")

    assert resp.status_code == 200
    assert b"Last batch" not in resp.data
