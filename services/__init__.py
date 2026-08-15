from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Every service's check_balance() call MUST pass this as its requests
# timeout. Plain `requests.get(url)` with no timeout can hang forever on a
# slow/unresponsive API -- confirmed the hard way: a real scan sat
# indefinitely with zero progress and zero error, because the existing
# retry/backoff logic in tools/check_wallet_balances.py can only retry
# once a call actually returns or raises, and an untimed-out request never
# does either.
REQUEST_TIMEOUT_SECONDS = 15

class WalletService:
    """
    Base class for all wallet services. Each service must implement check_balance.
    """

    def check_balance(self, address):
        """
        Check the balance for a given address.
        :param address: The wallet address to query.
        :return: The balance as a float, or None if an error occurs.
        """
        raise NotImplementedError("Subclasses must implement this method.")