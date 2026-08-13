from unittest.mock import MagicMock, patch

from services.feathercoin import FeathercoinService

ADDRESS = "6ippTCFqa3SvVcwqVugge4VNozB5uPg3hS"


@patch("services.feathercoin.requests.get")
def test_check_balance_uses_the_trezor_blockbook_explorer(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"balance": "173481812749"}
    mock_get.return_value = mock_response

    balance = FeathercoinService().check_balance(ADDRESS)

    called_url = mock_get.call_args[0][0]
    assert called_url == f"https://explorer.feathercoin.com/api/v2/address/{ADDRESS}"
    assert balance == 1734.81812749


@patch("services.feathercoin.requests.get")
def test_check_balance_returns_none_on_non_200(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_get.return_value = mock_response

    assert FeathercoinService().check_balance(ADDRESS) is None


@patch("services.feathercoin.requests.get")
def test_check_balance_returns_none_on_request_exception(mock_get):
    import requests

    mock_get.side_effect = requests.RequestException("boom")

    assert FeathercoinService().check_balance(ADDRESS) is None
