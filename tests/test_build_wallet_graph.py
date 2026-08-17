from config.wallet import WALLET_SERVICES
from tools.build_wallet_graph import build_relationship_graph, render_graph_report


def test_duplicate_address_across_files_is_flagged():
    wallet_data = {
        "walletA.dat": {"Bitcoin": {"1abc": 0.5}},
        "walletB.dat": {"Bitcoin": {"1abc": 0.5}},
    }

    graph = build_relationship_graph(wallet_data)

    assert graph["signals"]["duplicate_addresses"]["1abc"] == ["walletA.dat", "walletB.dat"]


def test_address_seen_only_once_is_not_flagged_as_duplicate():
    wallet_data = {
        "walletA.dat": {"Bitcoin": {"1abc": 0.5}},
    }

    graph = build_relationship_graph(wallet_data)

    assert "1abc" not in graph["signals"]["duplicate_addresses"]


def test_multi_coin_file_is_flagged():
    wallet_data = {
        "exodus_backup.json": {
            "Bitcoin": {"1abc": 0.1},
            "Ethereum": {"0xabc": 0.0},
        },
    }

    graph = build_relationship_graph(wallet_data)

    assert graph["signals"]["multi_coin_files"]["exodus_backup.json"] == ["Bitcoin", "Ethereum"]


def test_single_coin_file_is_not_flagged_as_multi_coin():
    wallet_data = {
        "bitcoin_only.dat": {"Bitcoin": {"1abc": 0.1}},
    }

    graph = build_relationship_graph(wallet_data)

    assert "bitcoin_only.dat" not in graph["signals"]["multi_coin_files"]


def test_coverage_gap_lists_supported_coins_not_found_in_file():
    wallet_data = {
        "walletA.dat": {"Bitcoin": {"1abc": 0.1}},
    }

    graph = build_relationship_graph(wallet_data)

    gap = graph["signals"]["coverage_gaps"]["walletA.dat"]
    assert gap["found"] == ["Bitcoin"]
    assert set(gap["missing_supported_coins"]) == set(WALLET_SERVICES.keys()) - {"Bitcoin"}
    assert "Bitcoin" not in gap["missing_supported_coins"]


def test_file_covering_every_supported_coin_has_no_coverage_gap_entry():
    wallet_data = {
        "everything.dat": {coin: {"addr": None} for coin in WALLET_SERVICES.keys()},
    }

    graph = build_relationship_graph(wallet_data)

    assert "everything.dat" not in graph["signals"]["coverage_gaps"]


def test_none_balance_is_preserved_not_coerced_to_zero_or_dropped():
    wallet_data = {
        "walletA.dat": {"Bitcoin": {"1abc": None}},
    }

    graph = build_relationship_graph(wallet_data)

    matching_edges = [
        edge
        for edge in graph["edges"]["file_has_address"]
        if edge["file"] == "walletA.dat" and edge["address"] == "1abc"
    ]
    assert len(matching_edges) == 1
    assert matching_edges[0]["balance"] is None


def test_analysis_shape_list_of_addresses_is_accepted():
    # tools/analyze_wallets.py's shape: {file: {coin: [address, ...]}} -- no balances yet.
    wallet_data = {
        "walletA.dat": {"Bitcoin": ["1abc", "1def"]},
    }

    graph = build_relationship_graph(wallet_data)

    addresses = {edge["address"] for edge in graph["edges"]["file_has_address"]}
    assert addresses == {"1abc", "1def"}
    balances = {edge["balance"] for edge in graph["edges"]["file_has_address"]}
    assert balances == {None}


def test_balances_shape_dict_of_address_to_balance_is_accepted():
    # tools/check_wallet_balances.py's shape: {file: {coin: {address: balance}}}
    wallet_data = {
        "walletA.dat": {"Bitcoin": {"1abc": 1.5}},
    }

    graph = build_relationship_graph(wallet_data)

    edge = graph["edges"]["file_has_address"][0]
    assert edge == {"file": "walletA.dat", "address": "1abc", "coin": "Bitcoin", "balance": 1.5}


def test_nodes_are_deduplicated_across_files():
    wallet_data = {
        "walletA.dat": {"Bitcoin": {"1abc": 0.1}},
        "walletB.dat": {"Bitcoin": {"1abc": 0.1}, "Ethereum": {"0xdef": 0.0}},
    }

    graph = build_relationship_graph(wallet_data)

    assert sorted(graph["nodes"]["files"]) == ["walletA.dat", "walletB.dat"]
    assert sorted(graph["nodes"]["addresses"]) == ["0xdef", "1abc"]
    assert sorted(graph["nodes"]["coins"]) == ["Bitcoin", "Ethereum"]


def test_report_orders_duplicates_before_multi_coin_before_coverage_gaps():
    wallet_data = {
        "walletA.dat": {"Bitcoin": {"1abc": 0.1}},
        "walletB.dat": {"Bitcoin": {"1abc": 0.1}, "Ethereum": {"0xdef": 0.0}},
    }

    graph = build_relationship_graph(wallet_data)
    report = render_graph_report(graph)

    dup_pos = report.index("Duplicate")
    multi_pos = report.index("Multi-Coin")
    gap_pos = report.index("Coverage")
    assert dup_pos < multi_pos < gap_pos


def test_report_coverage_gap_copy_reads_as_a_nudge_not_an_assertion():
    wallet_data = {"walletA.dat": {"Bitcoin": {"1abc": 0.1}}}
    graph = build_relationship_graph(wallet_data)

    report = render_graph_report(graph)

    # Must not assert the wallet HAS the missing coins -- only suggest checking.
    assert "has Ethereum" not in report
    assert "?" in report or "you might" in report.lower() or "worth checking" in report.lower()
