import json
import threading
from unittest.mock import MagicMock, patch

import pytest

from tools.check_wallet_balances import _check_balance_with_retries, check_wallet_balances


def make_service(side_effect):
    service = MagicMock()
    service.check_balance = MagicMock(side_effect=side_effect)
    return service


@patch("tools.check_wallet_balances.time.sleep")
def test_immediate_success_does_not_retry(mock_sleep):
    service = make_service([5.0])

    result = _check_balance_with_retries(service, "addr", max_retries=3, backoff_seconds=2)

    assert result == 5.0
    assert service.check_balance.call_count == 1
    mock_sleep.assert_not_called()


@patch("tools.check_wallet_balances.time.sleep")
def test_eventual_success_stops_retrying_once_confirmed(mock_sleep):
    service = make_service([None, None, 3.0])

    result = _check_balance_with_retries(service, "addr", max_retries=3, backoff_seconds=2)

    assert result == 3.0
    assert service.check_balance.call_count == 3
    assert mock_sleep.call_count == 2


@patch("tools.check_wallet_balances.time.sleep")
def test_exhausted_retries_returns_none_without_sleeping_after_final_attempt(mock_sleep):
    service = make_service([None, None, None])

    result = _check_balance_with_retries(service, "addr", max_retries=3, backoff_seconds=2)

    assert result is None
    assert service.check_balance.call_count == 3
    assert mock_sleep.call_count == 2  # sleeps between attempts, never after the last


@patch("tools.check_wallet_balances.time.sleep")
def test_confirmed_zero_balance_is_not_retried(mock_sleep):
    service = make_service([0.0])

    result = _check_balance_with_retries(service, "addr", max_retries=3, backoff_seconds=2)

    assert result == 0.0
    assert service.check_balance.call_count == 1
    mock_sleep.assert_not_called()


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_inconclusive_address_after_retries_is_written_to_inconclusive_file(
    mock_load_service, mock_sleep, tmp_path
):
    mock_load_service.return_value = make_service([None, None, None])

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": ["1abc"]}}))
    output_file = tmp_path / "wallet_balances.json"

    check_wallet_balances(str(input_file), str(output_file), coins_to_check=["Bitcoin"])

    inconclusive_file = tmp_path / "inconclusive_balances.json"
    assert inconclusive_file.exists()
    assert json.loads(inconclusive_file.read_text()) == {"walletA.dat": {"Bitcoin": ["1abc"]}}


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_no_inconclusive_file_written_when_nothing_is_inconclusive(
    mock_load_service, mock_sleep, tmp_path
):
    mock_load_service.return_value = make_service([0.0])

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": ["1abc"]}}))
    output_file = tmp_path / "wallet_balances.json"

    check_wallet_balances(str(input_file), str(output_file), coins_to_check=["Bitcoin"])

    inconclusive_file = tmp_path / "inconclusive_balances.json"
    assert not inconclusive_file.exists()

    balances = json.loads(output_file.read_text())
    assert balances["walletA.dat"]["Bitcoin"]["1abc"] == 0.0


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_inconclusive_output_path_is_overridable(mock_load_service, mock_sleep, tmp_path):
    mock_load_service.return_value = make_service([None, None, None])

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": ["1abc"]}}))
    output_file = tmp_path / "wallet_balances.json"
    custom_inconclusive = tmp_path / "custom_inconclusive.json"

    check_wallet_balances(
        str(input_file),
        str(output_file),
        coins_to_check=["Bitcoin"],
        inconclusive_output=str(custom_inconclusive),
    )

    assert custom_inconclusive.exists()
    assert not (tmp_path / "inconclusive_balances.json").exists()


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_progress_callback_invoked_once_per_address(mock_load_service, mock_sleep, tmp_path):
    mock_load_service.return_value = make_service([0.0, 1.5])

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": ["1abc", "1def"]}}))
    output_file = tmp_path / "wallet_balances.json"

    calls = []
    check_wallet_balances(
        str(input_file),
        str(output_file),
        coins_to_check=["Bitcoin"],
        progress_callback=lambda current, total, message="": calls.append((current, total)),
    )

    assert calls == [(1, 2), (2, 2)]


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_no_progress_callback_is_unaffected(mock_load_service, mock_sleep, tmp_path):
    mock_load_service.return_value = make_service([0.0])

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": ["1abc"]}}))
    output_file = tmp_path / "wallet_balances.json"

    result = check_wallet_balances(str(input_file), str(output_file), coins_to_check=["Bitcoin"])

    assert result["walletA.dat"]["Bitcoin"]["1abc"] == 0.0


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_different_coins_are_checked_concurrently(mock_load_service, mock_sleep, tmp_path):
    """
    The real complaint this story fixes: every coin's own independent
    service/API used to be checked one at a time, in one thread. Two
    services here each block until the OTHER has started -- if coins are
    still checked serially, the second coin's worker never starts while
    the first is blocked waiting for it, so this deadlocks and times out.
    """
    bitcoin_started = threading.Event()
    litecoin_started = threading.Event()

    def make_blocking_service(own_started, other_started):
        def check_balance(address):
            own_started.set()
            assert other_started.wait(timeout=2), "the other coin's call never started -- coins are being checked serially, not concurrently"
            return 1.0

        service = MagicMock()
        service.check_balance = MagicMock(side_effect=check_balance)
        return service

    services = {
        "Bitcoin": make_blocking_service(bitcoin_started, litecoin_started),
        "Litecoin": make_blocking_service(litecoin_started, bitcoin_started),
    }
    mock_load_service.side_effect = lambda coin: services[coin]

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": ["1abc"], "Litecoin": ["Labc"]}}))
    output_file = tmp_path / "wallet_balances.json"

    result = check_wallet_balances(str(input_file), str(output_file), coins_to_check=["Bitcoin", "Litecoin"])

    assert result == {"walletA.dat": {"Bitcoin": {"1abc": 1.0}, "Litecoin": {"Labc": 1.0}}}


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_progress_callback_thread_safe_across_multiple_coins(mock_load_service, mock_sleep, tmp_path):
    mock_load_service.side_effect = lambda coin: MagicMock(check_balance=MagicMock(return_value=1.0))

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": ["1abc", "1def"], "Litecoin": ["Labc", "Ldef"]}}))
    output_file = tmp_path / "wallet_balances.json"

    calls = []
    calls_lock = threading.Lock()

    def cb(current, total, message=""):
        with calls_lock:
            calls.append((current, total))

    check_wallet_balances(str(input_file), str(output_file), coins_to_check=["Bitcoin", "Litecoin"], progress_callback=cb)

    assert len(calls) == 4
    assert all(total == 4 for _, total in calls)
    assert sorted(current for current, _ in calls) == [1, 2, 3, 4]


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_multi_coin_multi_file_output_matches_expected_nested_dict(mock_load_service, mock_sleep, tmp_path):
    values = {"Bitcoin": 1.0, "Litecoin": 2.0}
    mock_load_service.side_effect = lambda coin: MagicMock(check_balance=MagicMock(return_value=values[coin]))

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(
        json.dumps(
            {
                "walletA.dat": {"Bitcoin": ["1abc"], "Litecoin": ["Labc"]},
                "walletB.dat": {"Bitcoin": ["1def"]},
            }
        )
    )
    output_file = tmp_path / "wallet_balances.json"

    result = check_wallet_balances(str(input_file), str(output_file), coins_to_check=["Bitcoin", "Litecoin"])

    assert result == {
        "walletA.dat": {"Bitcoin": {"1abc": 1.0}, "Litecoin": {"Labc": 2.0}},
        "walletB.dat": {"Bitcoin": {"1def": 1.0}},
    }
