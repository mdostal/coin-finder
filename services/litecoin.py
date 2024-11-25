import requests
from . import WalletService

class LitecoinService(WalletService):
    def check_balance(self, address):
        try:
            url = f"https://api.blockcypher.com/v1/ltc/main/addrs/{address}/balance"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            data = response.json()
            return float(data.get("final_balance", 0)) / 1e8  # Convert litoshis to LTC
        except Exception as e:
            print(f"Error checking Litecoin balance: {e}")
            return None