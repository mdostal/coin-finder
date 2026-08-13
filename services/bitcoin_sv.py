import requests
from . import WalletService

class BitcoinSvService(WalletService):
    def check_balance(self, address):
        try:
            url = f"https://api.blockchair.com/bitcoin-sv/dashboards/address/{address}"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            data = response.json()
            return data.get("data", {}).get(address, {}).get("balance", 0) / 1e8
        except Exception as e:
            print(f"Error checking Bitcoin SV balance: {e}")
            return None
