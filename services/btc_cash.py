import requests
from . import WalletService

class BitcoinCashService(WalletService):
    def check_balance(self, address):
        try:
            url = f"https://api.blockchair.com/bitcoin-cash/dashboards/address/{address}"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            data = response.json()
            return data.get("data", {}).get(address, {}).get("balance", 0) / 1e8
        except Exception as e:
            print(f"Error checking Bitcoin Cash balance: {e}")
            return None