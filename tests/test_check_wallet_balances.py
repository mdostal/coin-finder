import json
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
