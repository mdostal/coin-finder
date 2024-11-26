import requests
import os
from . import WalletService

class CardanoService(WalletService):
    
    def __init__(self):
        # Fetch the API key from the environment variable
        self.api_key = os.getenv("BLOCKFROST_API_KEY")
        if not self.api_key:
            raise ValueError("BLOCKFROST_API_KEY is not set in the environment")

    def check_balance(self, address):
        try:
            url = f"https://cardano-mainnet.blockfrost.io/api/v0/addresses/{address}"
            headers = {"project_id": self.API_KEY}
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                return None
            data = response.json()
            total_balance = sum(
                int(amount["quantity"]) for amount in data.get("amount", [])
            )
            return total_balance / 1e6  # Convert lovelaces to ADA
        except Exception as e:
            print(f"Error checking Cardano balance: {e}")
            return None
