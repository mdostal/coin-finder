import requests
from . import WalletService

class RippleService(WalletService):
    def check_balance(self, address):
        try:
            url = f"https://data.ripple.com/v2/accounts/{address}/balances"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            data = response.json()
            for balance in data.get("balances", []):
                if balance.get("currency") == "XRP":
                    return float(balance.get("value", 0))
            return 0.0
        except Exception as e:
            print(f"Error checking Ripple balance: {e}")
            return None