import requests
import os
from . import WalletService

class ShibaInuService(WalletService):
    def __init__(self):
        # Fetch the API key from the environment variable
        self.api_key = os.getenv("ETHERSCAN_API_KEY")
        if not self.api_key:
            raise ValueError("ETHERSCAN_API_KEY is not set in the environment")

    def check_balance(self, address):
        try:
            # Shiba Inu is an ERC-20 token on Ethereum
            url = f"https://api.etherscan.io/api?module=account&action=tokenbalance&contractaddress=0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE&address={address}&tag=latest&apikey={self.api_key}"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            data = response.json()
            return int(data.get("result", 0)) / 1e18  # SHIB has 18 decimals
        except Exception as e:
            print(f"Error checking Shiba Inu balance: {e}")
            return None