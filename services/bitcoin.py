import requests
from . import WalletService

class BitcoinService(WalletService):
    def check_balance(self, address):
        try:
            url = f"https://blockstream.info/api/address/{address}"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            data = response.json()
            funded = data["chain_stats"]["funded_txo_sum"]
            spent = data["chain_stats"]["spent_txo_sum"]
            return (funded - spent) / 1e8  # Convert satoshis to BTC
        except Exception as e:
            print(f"Error checking Bitcoin balance: {e}")
            return None