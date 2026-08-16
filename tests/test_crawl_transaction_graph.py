import json
import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

from tools.crawl_transaction_graph import (
    compute_last_activity_timestamp,
    crawl_wallet_cluster,
    dormancy_years,
    find_co_spend_addresses,
    find_output_addresses,
    load_seed_addresses,
    render_cluster_report,
)

SEED = "1Seed00000000000000000000000000"
COSPEND = "1CoSpend0000000000000000000000"
THIRD_PARTY = "1ThirdParty000000000000000000"


def make_tx(vin_addresses, vout_addresses, block_time=None, confirmed=True):
    tx = {
        "txid": "fake",
        "vin": [
            {"prevout": {"scriptpubkey_address": addr}} for addr in vin_addresses
        ],
        "vout": [{"scriptpubkey_address": addr} for addr in vout_addresses],
    }
    if block_time is not None:
        tx["status"] = {"confirmed": confirmed, "block_time": block_time}
    return tx


def test_co_spend_addresses_found_when_known_address_is_an_input():
    tx = make_tx([SEED, COSPEND], [THIRD_PARTY])

    result = find_co_spend_addresses(tx, SEED)

    assert result == {COSPEND}


def test_co_spend_addresses_empty_when_known_address_not_an_input():
    tx = make_tx([COSPEND], [SEED])

    result = find_co_spend_addresses(tx, SEED)

    assert result == set()


def test_output_addresses_found_when_known_address_is_input_and_within_cap():
    tx = make_tx([SEED], [THIRD_PARTY, COSPEND])

    result = find_output_addresses(tx, SEED, max_outputs=20)

    assert result == {THIRD_PARTY, COSPEND}


def test_output_addresses_empty_when_tx_exceeds_max_outputs():
    many_outputs = [f"1Out{i:028d}" for i in range(21)]
    tx = make_tx([SEED], many_outputs)

    result = find_output_addresses(tx, SEED, max_outputs=20)

    assert result == set()


def test_output_addresses_empty_when_known_address_not_an_input():
    tx = make_tx([COSPEND], [THIRD_PARTY])

    result = find_output_addresses(tx, SEED, max_outputs=20)

    assert result == set()


@patch("tools.crawl_transaction_graph.BitcoinService")
@patch("tools.crawl_transaction_graph.fetch_address_transactions")
def test_crawl_discovers_co_spend_address_with_correct_confidence_and_generation(
    mock_fetch, mock_service_cls
):
    mock_fetch.side_effect = lambda addr: {
        SEED: [make_tx([SEED, COSPEND], [THIRD_PARTY])],
        COSPEND: [],
    }.get(addr, [])
    mock_service_cls.return_value.check_balance.return_value = 0.0

    result = crawl_wallet_cluster([SEED], max_generations=1)

    assert result[COSPEND]["confidence"] == "co-spend"
    assert result[COSPEND]["generation"] == 1


@patch("tools.crawl_transaction_graph.BitcoinService")
@patch("tools.crawl_transaction_graph.fetch_address_transactions")
def test_seed_has_no_discovered_via_parent(mock_fetch, mock_service_cls):
    mock_fetch.return_value = []
    mock_service_cls.return_value.check_balance.return_value = 0.0

    result = crawl_wallet_cluster([SEED], max_generations=1)

    assert result[SEED]["discovered_via"] is None


@patch("tools.crawl_transaction_graph.BitcoinService")
@patch("tools.crawl_transaction_graph.fetch_address_transactions")
def test_discovered_via_tracks_the_actual_parent_across_two_hops(mock_fetch, mock_service_cls):
    """
    seed -> COSPEND (gen 1, discovered via seed) -> GRANDCHILD (gen 2,
    discovered via COSPEND, NOT via seed) -- proves discovered_via
    records the real BFS parent, not just "whatever was in generation 0".
    """
    grandchild = "1GrandChild00000000000000000000"

    def fetch(addr):
        if addr == SEED:
            return [make_tx([SEED, COSPEND], [])]
        if addr == COSPEND:
            return [make_tx([COSPEND, grandchild], [])]
        return []

    mock_fetch.side_effect = fetch
    mock_service_cls.return_value.check_balance.return_value = 0.0

    result = crawl_wallet_cluster([SEED], max_generations=2)

    assert result[COSPEND]["discovered_via"] == SEED
    assert result[grandchild]["discovered_via"] == COSPEND


@patch("tools.crawl_transaction_graph.BitcoinService")
@patch("tools.crawl_transaction_graph.fetch_address_transactions")
def test_crawl_respects_max_addresses_cap_without_raising(mock_fetch, mock_service_cls):
    many_cospends = [f"1Co{i:029d}" for i in range(50)]

    def fetch(addr):
        if addr == SEED:
            return [make_tx([SEED] + many_cospends, [])]
        return []

    mock_fetch.side_effect = fetch
    mock_service_cls.return_value.check_balance.return_value = 0.0

    result = crawl_wallet_cluster([SEED], max_generations=1, max_addresses=10)

    assert len(result) <= 10


@patch("tools.crawl_transaction_graph.BitcoinService")
@patch("tools.crawl_transaction_graph.fetch_address_transactions")
def test_every_discovered_address_has_balance_populated_from_mocked_service(
    mock_fetch, mock_service_cls
):
    mock_fetch.side_effect = lambda addr: {
        SEED: [make_tx([SEED, COSPEND], [])],
        COSPEND: [],
    }.get(addr, [])
    mock_service_cls.return_value.check_balance.return_value = 1.5

    result = crawl_wallet_cluster([SEED], max_generations=1)

    assert result[SEED]["balance"] == 1.5
    assert result[COSPEND]["balance"] == 1.5
    assert result[SEED]["confidence"] == "seed"


def test_report_sorted_by_balance_descending_and_significant_tagged():
    results = {
        SEED: {"confidence": "seed", "generation": 0, "balance": 0.1},
        COSPEND: {"confidence": "co-spend", "generation": 1, "balance": 5.0},
        THIRD_PARTY: {"confidence": "output", "generation": 1, "balance": None},
    }

    report = render_cluster_report(results, balance_threshold=1.0)

    cospend_pos = report.index(COSPEND)
    seed_pos = report.index(SEED)
    third_party_pos = report.index(THIRD_PARTY)
    assert cospend_pos < seed_pos < third_party_pos
    assert f"SIGNIFICANT" in report
    assert report.count("SIGNIFICANT") == 1  # only the 5.0 BTC entry


def test_compute_last_activity_returns_max_block_time_among_confirmed_txs():
    txs = [
        make_tx([SEED], [], block_time=1000),
        make_tx([SEED], [], block_time=5000),
        make_tx([SEED], [], block_time=2000),
    ]

    assert compute_last_activity_timestamp(txs) == 5000


def test_compute_last_activity_ignores_unconfirmed_txs():
    txs = [
        make_tx([SEED], [], block_time=9999, confirmed=False),
        make_tx([SEED], [], block_time=1000, confirmed=True),
    ]

    assert compute_last_activity_timestamp(txs) == 1000


def test_compute_last_activity_returns_none_when_no_confirmed_txs():
    txs = [make_tx([SEED], [], block_time=9999, confirmed=False)]

    assert compute_last_activity_timestamp(txs) is None


def test_compute_last_activity_returns_none_for_empty_tx_list():
    assert compute_last_activity_timestamp([]) is None


def test_dormancy_years_computes_elapsed_time():
    one_year_seconds = 365.25 * 24 * 3600
    last_activity = 1000
    now = 1000 + (5 * one_year_seconds)

    result = dormancy_years(last_activity, now=now)

    assert 4.99 < result < 5.01


def test_dormancy_years_returns_none_when_last_activity_unknown():
    assert dormancy_years(None, now=1000) is None


@patch("tools.crawl_transaction_graph.BitcoinService")
@patch("tools.crawl_transaction_graph.fetch_address_transactions")
def test_crawl_populates_last_activity_and_dormancy_for_seed(mock_fetch, mock_service_cls):
    mock_fetch.side_effect = lambda addr: {
        SEED: [make_tx([SEED], [], block_time=1000)],
    }.get(addr, [])
    mock_service_cls.return_value.check_balance.return_value = 0.3

    one_year_seconds = 365.25 * 24 * 3600
    now = 1000 + (6 * one_year_seconds)
    result = crawl_wallet_cluster([SEED], max_generations=1, now=now)

    assert result[SEED]["last_activity_timestamp"] == 1000
    assert result[SEED]["dormant_years"] > 5


def test_report_never_asserts_certainty_for_output_confidence():
    results = {SEED: {"confidence": "output", "generation": 1, "balance": 2.0}}

    report = render_cluster_report(results)

    assert "confidence: output" in report


@patch("tools.crawl_transaction_graph.BitcoinService")
@patch("tools.crawl_transaction_graph.fetch_address_transactions")
def test_cli_writes_json_and_markdown_report(mock_fetch, mock_service_cls, tmp_path):
    # This test exercises the module functions directly (not via subprocess,
    # since the CLI makes real network/BitcoinService calls) -- see the
    # separate manual smoke-test note in the story for real-world CLI
    # verification against the actual found address.
    from tools.crawl_transaction_graph import crawl_wallet_cluster, render_cluster_report

    mock_fetch.return_value = []
    mock_service_cls.return_value.check_balance.return_value = 0.0

    results = crawl_wallet_cluster([SEED], max_generations=1)
    output_file = tmp_path / "cluster.json"
    report_file = tmp_path / "cluster.md"

    with open(output_file, "w") as f:
        json.dump(results, f)
    with open(report_file, "w") as f:
        f.write(render_cluster_report(results))

    assert output_file.exists()
    assert report_file.exists()
    assert json.loads(output_file.read_text())[SEED]["confidence"] == "seed"


@patch("tools.crawl_transaction_graph.BitcoinService")
@patch("tools.crawl_transaction_graph.fetch_address_transactions")
def test_edges_out_none_is_a_complete_no_op(mock_fetch, mock_service_cls):
    mock_fetch.side_effect = lambda addr: {SEED: [make_tx([SEED, COSPEND], [])]}.get(addr, [])
    mock_service_cls.return_value.check_balance.return_value = 0.0

    result = crawl_wallet_cluster([SEED], max_generations=1, edges_out=None)

    assert result[COSPEND]["confidence"] == "co-spend"


@patch("tools.crawl_transaction_graph.BitcoinService")
@patch("tools.crawl_transaction_graph.fetch_address_transactions")
def test_edges_out_records_co_spend_edge(mock_fetch, mock_service_cls):
    tx = make_tx([SEED, COSPEND], [])
    tx["txid"] = "tx1"
    mock_fetch.side_effect = lambda addr: {SEED: [tx]}.get(addr, [])
    mock_service_cls.return_value.check_balance.return_value = 0.0

    edges = []
    crawl_wallet_cluster([SEED], max_generations=1, edges_out=edges)

    assert {"from": min(SEED, COSPEND), "to": max(SEED, COSPEND), "type": "co-spend", "txid": "tx1"} in edges


@patch("tools.crawl_transaction_graph.BitcoinService")
@patch("tools.crawl_transaction_graph.fetch_address_transactions")
def test_edges_out_records_output_edge_with_direction_preserved(mock_fetch, mock_service_cls):
    tx = make_tx([SEED], [THIRD_PARTY])
    tx["txid"] = "tx1"
    mock_fetch.side_effect = lambda addr: {SEED: [tx]}.get(addr, [])
    mock_service_cls.return_value.check_balance.return_value = 0.0

    edges = []
    crawl_wallet_cluster([SEED], max_generations=1, edges_out=edges)

    assert {"from": SEED, "to": THIRD_PARTY, "type": "output", "txid": "tx1"} in edges


@patch("tools.crawl_transaction_graph.BitcoinService")
@patch("tools.crawl_transaction_graph.fetch_address_transactions")
def test_edges_out_normalizes_co_spend_regardless_of_discovery_order(mock_fetch, mock_service_cls):
    """
    The double-counting risk called out in the design discussion: SEED's
    own scan finds a co-spend with COSPEND on tx1; COSPEND's own later
    scan (once it enters the frontier in generation 2) ALSO sees tx1 and
    would independently find the same co-spend relationship from the
    other side. Both must normalize to the SAME edge dict, not two
    directionally-swapped duplicates.
    """
    tx1 = make_tx([SEED, COSPEND], [])
    tx1["txid"] = "tx1"

    def fetch(addr):
        if addr == SEED:
            return [tx1]
        if addr == COSPEND:
            return [tx1]
        return []

    mock_fetch.side_effect = fetch
    mock_service_cls.return_value.check_balance.return_value = 0.0

    edges = []
    crawl_wallet_cluster([SEED], max_generations=2, edges_out=edges)

    cospend_edges = [e for e in edges if e["type"] == "co-spend"]
    assert cospend_edges == [{"from": min(SEED, COSPEND), "to": max(SEED, COSPEND), "type": "co-spend", "txid": "tx1"}]


def test_load_seed_addresses_returns_single_literal_address_unchanged():
    assert load_seed_addresses(SEED) == [SEED]


def test_load_seed_addresses_reads_multiple_addresses_from_a_file(tmp_path):
    seeds_file = tmp_path / "seeds.txt"
    seeds_file.write_text(f"# found on disk\n{SEED}\n\n# currently held\n{COSPEND}\n")

    result = load_seed_addresses(str(seeds_file))

    assert result == [SEED, COSPEND]


@patch("tools.crawl_transaction_graph.BitcoinService")
@patch("tools.crawl_transaction_graph.fetch_address_transactions")
def test_crawl_accepts_multiple_seeds_mixing_disk_and_held_addresses(mock_fetch, mock_service_cls):
    mock_fetch.return_value = []
    mock_service_cls.return_value.check_balance.return_value = 0.0

    result = crawl_wallet_cluster(load_seed_addresses(SEED) + [COSPEND], max_generations=1)

    assert result[SEED]["confidence"] == "seed"
    assert result[COSPEND]["confidence"] == "seed"
