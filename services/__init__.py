from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

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