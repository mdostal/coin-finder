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


# --- ccu-03: credential-completeness badge (extractable / encrypted-locked / not-applicable) ---


@patch("web.app.credential_status_index")
@patch("web.app.list_findings")
def test_findings_page_credential_badge_extractable_for_unencrypted_key(mock_list, mock_credential, client, tmp_path):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.0, "source_path": str(wallet_file), "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0, "watched": 0, "watch_note": ""}
    ]
    mock_credential.return_value = {str(wallet_file): {"is_wallet_dat": True, "error": None, "addresses": {"1abc": "key"}}}

    resp = client.get("/findings")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "key extractable, no password needed" in body
    assert "credential-extractable" in body
    assert "encrypted, no known password" not in body


@patch("web.app.credential_status_index")
@patch("web.app.list_findings")
def test_findings_page_credential_badge_encrypted_for_ckey(mock_list, mock_credential, client, tmp_path):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.0, "source_path": str(wallet_file), "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0, "watched": 0, "watch_note": ""}
    ]
    mock_credential.return_value = {str(wallet_file): {"is_wallet_dat": True, "error": None, "addresses": {"1abc": "ckey"}}}

    resp = client.get("/findings")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "encrypted, no known password" in body
    assert "credential-encrypted" in body
    assert "key extractable, no password needed" not in body


@patch("web.app.credential_status_index", return_value={})
@patch("web.app.list_findings")
def test_findings_page_credential_badge_not_applicable_for_non_bitcoin_coin(mock_list, mock_credential, client):
    mock_list.return_value = [
        {"coin": "Ethereum", "address": "0xabc", "balance": 0.0, "source_path": "/somewhere/wallet.dat", "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0, "watched": 0, "watch_note": ""}
    ]

    resp = client.get("/findings")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "not checked / not applicable" in body
    assert "credential-not-applicable" in body
    assert "encrypted, no known password" not in body
    assert "key extractable, no password needed" not in body


@patch("web.app.credential_status_index", return_value={})
@patch("web.app.list_findings")
def test_findings_page_credential_badge_not_applicable_for_missing_source_path(mock_list, mock_credential, client, tmp_path):
    missing_path = str(tmp_path / "moved-or-deleted.dat")
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.0, "source_path": missing_path, "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0, "watched": 0, "watch_note": ""}
    ]

    resp = client.get("/findings")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "not checked / not applicable" in body
    assert "credential-not-applicable" in body


@patch("web.app.credential_status_index", return_value={})
@patch("web.app.list_findings")
def test_findings_page_credential_badge_not_applicable_for_finding_without_source_path(mock_list, mock_credential, client):
    """
    Unlike ccu-02's unlock badge (hidden entirely without a source_path),
    the credential badge must always render -- "no source_path" is
    itself one of the explicit not-applicable reasons, and hiding the
    badge here would look identical to a page that simply hasn't loaded
    it yet.
    """
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.0, "source_path": None, "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0, "watched": 0, "watch_note": ""}
    ]

    resp = client.get("/findings")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "credential-not-applicable" in body


@patch("web.app.credential_status_index", return_value={})
@patch("web.app.list_findings")
def test_findings_page_credential_badge_not_applicable_when_bitcoin_wallet_never_scanned(mock_list, mock_credential, client, tmp_path):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.0, "source_path": str(wallet_file), "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0, "watched": 0, "watch_note": ""}
    ]

    resp = client.get("/findings")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # Eligible but never scanned still shows the SAME visual not-applicable
    # state (per the design's 4-state model) -- not a false "encrypted."
    assert "credential-not-applicable" in body
    assert "encrypted, no known password" not in body


@patch("web.app.credential_status_index")
@patch("web.app.list_findings")
def test_findings_page_credential_badge_not_applicable_for_recognized_but_not_wallet_dat_file(mock_list, mock_credential, client, tmp_path):
    wallet_file = tmp_path / "electrum.dat"
    wallet_file.write_bytes(b"x")
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.0, "source_path": str(wallet_file), "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0, "watched": 0, "watch_note": ""}
    ]
    mock_credential.return_value = {str(wallet_file): {"is_wallet_dat": False, "error": "not a recognized Bitcoin Core wallet.dat (Btree v9)", "addresses": {}}}

    resp = client.get("/findings")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "credential-not-applicable" in body
    assert "encrypted, no known password" not in body


@patch("web.app.credential_status_index")
@patch("web.app.latest_status_by_wallet_path")
@patch("web.app.list_auto_unlock_history", return_value=[])
@patch("web.app.list_findings")
def test_findings_page_credential_and_password_known_badges_are_independent_and_both_shown(
    mock_list, mock_history, mock_latest, mock_credential, client, tmp_path
):
    """
    A wallet can have a known password (ccu-02) AND still have an
    unencrypted/encrypted key fact for a given address (ccu-03) -- two
    independent signals, both shown, never collapsed into one badge.
    """
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.0, "source_path": str(wallet_file), "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0, "watched": 0, "watch_note": ""}
    ]
    mock_latest.return_value = {str(wallet_file): {"matched": True, "vault_label": "password-1", "run_at": 100.0}}
    mock_credential.return_value = {str(wallet_file): {"is_wallet_dat": True, "error": None, "addresses": {"1abc": "ckey"}}}

    resp = client.get("/findings")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "unlocked" in body
    assert "encrypted, no known password" in body


@patch("web.app.credential_status_index", return_value={})
@patch("web.app.list_findings")
def test_findings_page_offers_check_credential_status_bulk_action(mock_list, mock_credential, client):
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.0, "source_path": None, "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0, "watched": 0, "watch_note": ""}
    ]
    resp = client.get("/findings")

    assert resp.status_code == 200
    assert b'id="bulk-check-credential-status"' in resp.data


def test_not_applicable_and_encrypted_locked_badges_are_visually_and_textually_distinct():
    """
    The story's named risk: collapsing "not checked / not applicable"
    into the same look as "checked, genuinely encrypted" would make a
    user skip past a wallet they could actually recover. Asserted here
    directly against the CSS, independent of any one page render.
    """
    style_css = open("web/static/style.css").read()

    assert ".credential-not-applicable" in style_css
    assert ".credential-encrypted" in style_css
    not_applicable_rule = style_css.split(".credential-not-applicable", 1)[1].split("}", 1)[0]
    encrypted_rule = style_css.split(".credential-encrypted", 1)[1].split("}", 1)[0]
    assert not_applicable_rule != encrypted_rule
    # not-applicable must NOT use the same alarm-red error color the
    # encrypted-locked state uses -- that's the exact collapse this
    # story's risk section calls out.
    assert "var(--error)" not in not_applicable_rule
    assert "var(--error)" in encrypted_rule


# --- bpk-01: "key extracted" badge state + bulk-select checkbox candidate attribute ---


@patch("web.app.credential_status_index")
@patch("web.app.list_findings")
def test_findings_page_credential_badge_key_extracted_when_extracted_at_set(mock_list, mock_credential, client, tmp_path):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.0, "source_path": str(wallet_file), "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0, "watched": 0, "watch_note": ""}
    ]
    mock_credential.return_value = {
        str(wallet_file): {
            "is_wallet_dat": True,
            "error": None,
            "addresses": {"1abc": "key"},
            "extracted_at": {"1abc": 1700000000.0},
        }
    }

    resp = client.get("/findings")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "key extracted" in body
    assert "credential-extracted" in body
    # Must not simultaneously claim the never-extracted state.
    assert "key extractable, no password needed" not in body


@patch("web.app.credential_status_index")
@patch("web.app.list_findings")
def test_findings_page_credential_badge_key_extractable_when_never_extracted(mock_list, mock_credential, client, tmp_path):
    """
    key_type == 'key' but extracted_at is None (or the wallet_scan dict
    doesn't even carry an 'extracted_at' entry for this address) must
    still render the original never-extracted state, not the new one.
    """
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.0, "source_path": str(wallet_file), "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0, "watched": 0, "watch_note": ""}
    ]
    mock_credential.return_value = {
        str(wallet_file): {"is_wallet_dat": True, "error": None, "addresses": {"1abc": "key"}, "extracted_at": {"1abc": None}}
    }

    resp = client.get("/findings")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "key extractable, no password needed" in body
    assert "credential-extractable" in body
    assert "key extracted<" not in body


@patch("web.app.credential_status_index")
@patch("web.app.list_findings")
def test_findings_page_credential_badge_key_extractable_when_extracted_at_key_missing(mock_list, mock_credential, client, tmp_path):
    """
    Backward-compat: a wallet_scan dict with no 'extracted_at' entry at
    all (e.g. an older/mocked shape) must not error and must fall back
    to the never-extracted rendering, never crash the page.
    """
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.0, "source_path": str(wallet_file), "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0, "watched": 0, "watch_note": ""}
    ]
    mock_credential.return_value = {str(wallet_file): {"is_wallet_dat": True, "error": None, "addresses": {"1abc": "key"}}}

    resp = client.get("/findings")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "key extractable, no password needed" in body


@patch("web.app.credential_status_index")
@patch("web.app.list_findings")
def test_findings_page_checkbox_data_key_extractable_set_for_key_type(mock_list, mock_credential, client, tmp_path):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.0, "source_path": str(wallet_file), "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0, "watched": 0, "watch_note": ""}
    ]
    mock_credential.return_value = {
        str(wallet_file): {"is_wallet_dat": True, "error": None, "addresses": {"1abc": "key"}, "extracted_at": {"1abc": None}}
    }

    resp = client.get("/findings")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert 'data-key-extractable="1"' in body


@patch("web.app.credential_status_index")
@patch("web.app.list_findings")
def test_findings_page_checkbox_data_key_extractable_unset_for_ckey(mock_list, mock_credential, client, tmp_path):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"x")
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.0, "source_path": str(wallet_file), "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0, "watched": 0, "watch_note": ""}
    ]
    mock_credential.return_value = {
        str(wallet_file): {"is_wallet_dat": True, "error": None, "addresses": {"1abc": "ckey"}, "extracted_at": {}}
    }

    resp = client.get("/findings")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert 'data-key-extractable="0"' in body
    assert 'data-key-extractable="1"' not in body


@patch("web.app.credential_status_index", return_value={})
@patch("web.app.list_findings")
def test_findings_page_checkbox_data_key_extractable_unset_when_never_scanned(mock_list, mock_credential, client):
    mock_list.return_value = [
        {"coin": "Bitcoin", "address": "1abc", "balance": 0.0, "source_path": "/never-scanned.dat", "source_label": None, "status": "new", "first_seen_at": 0, "last_checked_at": 0, "watched": 0, "watch_note": ""}
    ]

    resp = client.get("/findings")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert 'data-key-extractable="0"' in body


def test_credential_extracted_badge_css_is_visually_distinct_from_extractable():
    """
    'key extracted' and 'key extractable, no password needed' are two
    different facts (already-copied-out vs. never-touched) -- the CSS
    must not render them identically, mirroring the not-applicable/
    encrypted distinctness test above.
    """
    style_css = open("web/static/style.css").read()

    assert ".credential-extracted" in style_css
    assert ".credential-extractable" in style_css
    extracted_rule = style_css.split(".credential-extracted", 1)[1].split("}", 1)[0]
    extractable_rule = style_css.split(".credential-extractable", 1)[1].split("}", 1)[0]
    assert extracted_rule != extractable_rule
