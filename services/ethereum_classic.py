import requests
from . import WalletService

class EthereumClassicService(WalletService):
    def check_balance(self, address):
        try:
            # Blockscout API endpoint for Ethereum Classic
            url = f"https://blockscout.com/etc/mainnet/api?module=account&action=balance&address={address}"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            data = response.json()
            # Balance is returned in wei; convert to ETC
            return float(data.get("result", 0)) / 1e18
        except Exception as e:
            print(f"Error checking Ethereum Classic balance: {e}")
            return None