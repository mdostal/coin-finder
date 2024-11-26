import requests
from . import WalletService

class DmdService(WalletService):
    def check_balance(self, address):
        try:
            # Example API endpoint for DMD blockchain explorer
            url = f"https://explorer.dmdcoin.com/api/addr/{address}/balance"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            # Balance is returned in DMD
            return float(response.text)
        except Exception as e:
            print(f"Error checking Diamond Coin (DMD) balance: {e}")
            return None