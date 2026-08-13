import requests
from . import WalletService

class BitcoinGoldService(WalletService):
    def check_balance(self, address):
        try:
            url = f"https://api.blockchair.com/bitcoin-gold/dashboards/address/{address}"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            data = response.json()
            return data.get("data", {}).get(address, {}).get("balance", 0) / 1e8  # Convert satoshis to BTG
        except Exception as e:
            print(f"Error checking Bitcoin Gold balance: {e}")
            return None