from unittest.mock import MagicMock, patch

from services.bitcoin_sv import BitcoinSvService

ADDRESS = "1GcWwQTb4giriXRmEjdizaXnyy5ABpKCpB"


@patch("services.bitcoin_sv.requests.get")
def test_check_balance_uses_the_blockchair_api_host(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": {ADDRESS: {"balance": 150000000}}}
    mock_get.return_value = mock_response

    balance = BitcoinSvService().check_balance(ADDRESS)

    called_url = mock_get.call_args[0][0]
    assert called_url.startswith("https://api.blockchair.com/bitcoin-sv/")
    assert balance == 1.5


@patch("services.bitcoin_sv.requests.get")
def test_check_balance_returns_none_on_non_200(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_get.return_value = mock_response

    assert BitcoinSvService().check_balance(ADDRESS) is None


@patch("services.bitcoin_sv.requests.get")
def test_check_balance_returns_none_on_request_exception(mock_get):
    import requests

    mock_get.side_effect = requests.RequestException("boom")

    assert BitcoinSvService().check_balance(ADDRESS) is None
