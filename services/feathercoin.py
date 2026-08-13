import requests
from . import WalletService

class FeathercoinService(WalletService):
    def check_balance(self, address):
        try:
            url = f"https://explorer.feathercoin.com/api/v2/address/{address}"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            data = response.json()
            return int(data.get("balance", 0)) / 1e8
        except Exception as e:
            print(f"Error checking Feathercoin balance: {e}")
            return None
