import requests
from . import WalletService

class DigibyteService(WalletService):
    def check_balance(self, address):
        try:
            # Chainz Explorer API endpoint for Digibyte
            url = f"https://chainz.cryptoid.info/dgb/api.dws?q=getbalance&a={address}"
            response = requests.get(url)
            if response.status_code != 200:
                print(f"Error: Received status code {response.status_code} from API.")
                return None

            # Parse the balance directly (response is in DGB units)
            return float(response.text)
        except Exception as e:
            print(f"Error checking Digibyte balance: {e}")
            return None