import requests
from . import REQUEST_TIMEOUT_SECONDS, WalletService

class OkcashService(WalletService):
    def check_balance(self, address):
        try:
            # Chainz Explorer API endpoint for Okcash
            url = f"https://chainz.cryptoid.info/ok/api.dws?q=getbalance&a={address}"
            response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            if response.status_code != 200:
                print(f"Error: Received status code {response.status_code} from API.")
                return None

            # Parse the balance directly (response is in OK units)
            return float(response.text)
        except Exception as e:
            print(f"Error checking Okcash balance: {e}")
            return None