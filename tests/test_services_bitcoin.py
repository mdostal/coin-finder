from unittest.mock import MagicMock, patch

from services.bitcoin import BitcoinService

ADDRESS = "1GcWwQTb4giriXRmEjdizaXnyy5ABpKCpB"


def _response(status_code, chain_stats=None):
    resp = MagicMock()
    resp.status_code = status_code
    if chain_stats is not None:
        resp.json.return_value = {"chain_stats": chain_stats}
    return resp


@patch("services.bitcoin.requests.get")
def test_check_balance_uses_blockstream_first(mock_get):
    mock_get.return_value = _response(200, {"funded_txo_sum": 50000000, "spent_txo_sum": 20000000})

    balance = BitcoinService().check_balance(ADDRESS)

    called_url = mock_get.call_args[0][0]
    assert called_url.startswith("https://blockstream.info/")
    assert balance == 0.3
    assert mock_get.call_count == 1


@patch("services.bitcoin.requests.get")
def test_check_balance_falls_back_to_mempool_space_on_blockstream_failure(mock_get):
    """
    Regression test for a real bug hit live: blockstream.info's free
    tier caps unauthenticated usage at 700 requests/hour/IP -- heavy
    real-world use of this tool hit that wall mid-session (429 Too Many
    Requests), and every balance check failed until the hourly window
    reset. mempool.space runs the identical open-source backend
    (confirmed live: same API shape, same real data for a real address)
    on a separate host with its own rate-limit pool -- a free fallback
    for exactly this failure mode.
    """
    mock_get.side_effect = [
        _response(429),  # blockstream.info rate-limited
        _response(200, {"funded_txo_sum": 44166927, "spent_txo_sum": 14167869}),  # mempool.space succeeds
    ]

    balance = BitcoinService().check_balance(ADDRESS)

    assert mock_get.call_count == 2
    first_url = mock_get.call_args_list[0][0][0]
    second_url = mock_get.call_args_list[1][0][0]
    assert first_url.startswith("https://blockstream.info/")
    assert second_url.startswith("https://mempool.space/")
    assert balance == 0.29999058


@patch("services.bitcoin.requests.get")
def test_check_balance_returns_none_when_both_hosts_fail(mock_get):
    mock_get.side_effect = [_response(429), _response(500)]

    assert BitcoinService().check_balance(ADDRESS) is None
    assert mock_get.call_count == 2


@patch("services.bitcoin.requests.get")
def test_check_balance_returns_none_on_request_exception_from_both_hosts(mock_get):
    mock_get.side_effect = ConnectionError("no network")

    assert BitcoinService().check_balance(ADDRESS) is None
    assert mock_get.call_count == 2
