import requests
from . import WalletService

class DogecoinService(WalletService):
    def check_balance(self, address):
        try:
            # Blockchair API endpoint for Dogecoin
            url = f"https://api.blockchair.com/dogecoin/dashboards/address/{address}"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            data = response.json()

            # Extract the balance (Blockchair provides balance in satoshis)
            balance_satoshis = data.get("data", {}).get(address, {}).get("address", {}).get("balance", 0)
            return balance_satoshis / 1e8  # Convert satoshis to DOGE
        except Exception as e:
            print(f"Error checking Dogecoin balance: {e}")
            return None