import json
from unittest.mock import MagicMock, patch

from tools.check_fork_coins import (
    FORK_COINS,
    check_fork_coin_balances,
    check_fork_coins_for_addresses,
    load_addresses_from_file,
    render_fork_coin_report,
)

ADDRESS = "1GcWwQTb4giriXRmEjdizaXnyy5ABpKCpB"
ADDRESS_2 = "1MAVqESJxwtseFhH6iTAMDsk4hTzX4hbA4"


@patch("tools.check_fork_coins.load_service")
def test_check_fork_coin_balances_checks_every_fork_coin(mock_load_service):
    fake_service = MagicMock()
    fake_service.check_balance.return_value = 0.0
    mock_load_service.return_value = fake_service

    result = check_fork_coin_balances(ADDRESS)

    assert set(result.keys()) == set(FORK_COINS)
    assert mock_load_service.call_count == len(FORK_COINS)


@patch("tools.check_fork_coins.load_service")
def test_check_fork_coin_balances_reflects_a_nonzero_hit(mock_load_service):
    def service_for(coin):
        service = MagicMock()
        service.check_balance.return_value = 0.02 if coin == "Bitcoin Gold" else 0.0
        return service

    mock_load_service.side_effect = service_for

    result = check_fork_coin_balances(ADDRESS)

    assert result["Bitcoin Gold"] == 0.02
    assert result["Bitcoin Cash"] == 0.0


@patch("tools.check_fork_coins.load_service")
def test_check_fork_coin_balances_handles_unavailable_service_gracefully(mock_load_service):
    mock_load_service.return_value = None

    result = check_fork_coin_balances(ADDRESS)

    assert all(balance is None for balance in result.values())


@patch("tools.check_fork_coins.check_fork_coin_balances")
def test_check_fork_coins_for_addresses_covers_every_address(mock_check_one):
    mock_check_one.return_value = {"Bitcoin Cash": 0.0, "Bitcoin Gold": 0.0}

    result = check_fork_coins_for_addresses([ADDRESS, ADDRESS_2])

    assert set(result.keys()) == {ADDRESS, ADDRESS_2}
    assert mock_check_one.call_count == 2


def test_load_addresses_from_scan_wallet_dat_output_shape(tmp_path):
    input_file = tmp_path / "scan.json"
    input_file.write_text(json.dumps({"results": [{"address": ADDRESS, "balance": 0.3}, {"address": ADDRESS_2, "balance": 0.0}]}))

    assert load_addresses_from_file(str(input_file)) == [ADDRESS, ADDRESS_2]


def test_load_addresses_from_crawl_transaction_graph_output_shape(tmp_path):
    input_file = tmp_path / "cluster.json"
    input_file.write_text(json.dumps({ADDRESS: {"confidence": "seed"}, ADDRESS_2: {"confidence": "co-spend"}}))

    assert sorted(load_addresses_from_file(str(input_file))) == sorted([ADDRESS, ADDRESS_2])


def test_load_addresses_from_plain_newline_file(tmp_path):
    input_file = tmp_path / "addresses.txt"
    input_file.write_text(f"{ADDRESS}\n{ADDRESS_2}\n")

    assert load_addresses_from_file(str(input_file)) == [ADDRESS, ADDRESS_2]


def test_report_highlights_any_nonzero_fork_coin_balance():
    results = {
        ADDRESS: {"Bitcoin Cash": 0.0, "Bitcoin Gold": 0.05},
        ADDRESS_2: {"Bitcoin Cash": 0.0, "Bitcoin Gold": 0.0},
    }

    report = render_fork_coin_report(results)

    assert "SIGNIFICANT" in report or "worth checking" in report.lower()
    assert ADDRESS in report
    assert "Bitcoin Gold" in report
