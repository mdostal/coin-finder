import requests
from . import WalletService

class BinanceCoinService(WalletService):
    def check_balance(self, address):
        try:
            url = f"https://api.binance.org/v1/account/{address}"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            data = response.json()
            return float(data.get("balances", [{}])[0].get("free", 0))
        except Exception as e:
            print(f"Error checking Binance Coin balance: {e}")
            return None
