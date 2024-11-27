import requests
from . import WalletService

class DmdService(WalletService):
    def check_balance(self, address):
        try:
            # New API endpoint for Chainz Explorer
            url = f"https://chainz.cryptoid.info/dmd/api.dws?q=getbalance&a={address}"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            # Parse the balance directly (response is in DMD units)
            return float(response.text)
        except Exception as e:
            print(f"Error checking Diamond Coin (DMD) balance: {e}")
            return None