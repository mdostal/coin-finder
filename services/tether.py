import requests
import os
from . import WalletService

class TetherService(WalletService):
    def __init__(self):
        # Fetch the API key from the environment variable
        self.api_key = os.getenv("ETHERSCAN_API_KEY")
        if not self.api_key:
            raise ValueError("ETHERSCAN_API_KEY is not set in the environment")

    def check_balance(self, address):
        try:
            # Tether exists on multiple chains; this example uses Ethereum
            url = f"https://api.etherscan.io/api?module=account&action=tokenbalance&contractaddress=0xdac17f958d2ee523a2206206994597c13d831ec7&address={address}&tag=latest&apikey={self.api_key}"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            data = response.json()
            return int(data.get("result", 0)) / 1e6  # USDT has 6 decimals
        except Exception as e:
            print(f"Error checking Tether balance: {e}")
            return None