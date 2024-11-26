
import requests
from . import WalletService

class IotaService(WalletService):
    def check_balance(self, address):
        try:
            url = f"https://explorer.iota.org/mainnet/api/v1/addresses/{address}"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            data = response.json()
            return data.get("data", {}).get("balance", 0)
        except Exception as e:
            print(f"Error checking IOTA balance: {e}")
            return None