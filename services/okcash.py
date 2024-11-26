
import requests
from . import WalletService

class OkcashService(WalletService):
    def check_balance(self, address):
        try:
            url = f"https://okcash.network/api/address/{address}"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            data = response.json()
            return data.get("balance", 0)
        except Exception as e:
            print(f"Error checking Okcash balance: {e}")
            return None