import requests
from . import WalletService

class DogecoinService(WalletService):
    def check_balance(self, address):
        try:
            url = f"https://sochain.com/api/v2/get_address_balance/DOGE/{address}"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            data = response.json()
            return float(data["data"]["confirmed_balance"])
        except Exception as e:
            print(f"Error checking Dogecoin balance: {e}")
            return None
