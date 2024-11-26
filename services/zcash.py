import requests
from . import WalletService

class ZcashService(WalletService):
    def check_balance(self, address):
        try:
            url = f"https://api.zcha.in/v2/mainnet/accounts/{address}"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            data = response.json()
            return float(data.get("balance", 0)) / 1e8
        except Exception as e:
            print(f"Error checking Zcash balance: {e}")
            return None