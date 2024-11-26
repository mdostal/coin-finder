import requests
from . import WalletService

class HeliumService(WalletService):
    def check_balance(self, address):
        try:
            url = f"https://api.helium.io/v1/accounts/{address}"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            data = response.json()
            return data.get("data", {}).get("balance", 0) / 1e8  # Convert to HNT
        except Exception as e:
            print(f"Error checking Helium balance: {e}")
            return None