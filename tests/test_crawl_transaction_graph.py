from unittest.mock import MagicMock, patch

from tools.crawl_transaction_graph import (
    crawl_wallet_cluster,
    find_co_spend_addresses,
    find_output_addresses,
)

SEED = "1Seed00000000000000000000000000"
COSPEND = "1CoSpend0000000000000000000000"
THIRD_PARTY = "1ThirdParty000000000000000000"


def make_tx(vin_addresses, vout_addresses):
    return {
        "txid": "fake",
        "vin": [
            {"prevout": {"scriptpubkey_address": addr}} for addr in vin_addresses
        ],
        "vout": [{"scriptpubkey_address": addr} for addr in vout_addresses],
    }


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
