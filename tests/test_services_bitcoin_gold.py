from unittest.mock import MagicMock, patch

from services.bitcoin_gold import BitcoinGoldService

ADDRESS = "GTQ9nddCsDFCUdrj9DUUgWVJfBTBGtC7DH"


@patch("services.bitcoin_gold.requests.get")
def test_check_balance_uses_the_api_host_not_the_webpage_host(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": {ADDRESS: {"balance": 150000000}}}
    mock_get.return_value = mock_response

    balance = BitcoinGoldService().check_balance(ADDRESS)

    called_url = mock_get.call_args[0][0]
    assert called_url.startswith("https://api.blockchair.com/")
    assert balance == 1.5


@patch("services.bitcoin_gold.requests.get")
def test_check_balance_returns_none_on_non_200(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_get.return_value = mock_response

    assert BitcoinGoldService().check_balance(ADDRESS) is None
