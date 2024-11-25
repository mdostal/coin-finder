import os
import requests
from . import WalletService

class EthereumService(WalletService):
    def __init__(self):
        # Fetch the API key from the environment variable
        self.api_key = os.getenv("ETHERSCAN_API_KEY")
        if not self.api_key:
            raise ValueError("ETHERSCAN_API_KEY is not set in the environment")

    def check_balance(self, address):
        try:
            url = f"https://api.etherscan.io/api?module=account&action=balance&address={address}&tag=latest&apikey={self.api_key}"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            data = response.json()
            return float(data.get("result", 0)) / 1e18  # Convert wei to ETH
        except Exception as e:
            print(f"Error checking Ethereum balance: {e}")
            return None
