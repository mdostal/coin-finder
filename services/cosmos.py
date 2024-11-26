import requests
from . import WalletService

class CosmosService(WalletService):
    def check_balance(self, address):
        try:
            url = f"https://api.mintscan.io/v1/accounts/{address}"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            data = response.json()
            return float(data.get("balances", [{}])[0].get("amount", 0)) / 1e6
        except Exception as e:
            print(f"Error checking Cosmos balance: {e}")
            return None