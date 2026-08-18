import requests
from . import REQUEST_TIMEOUT_SECONDS, WalletService

# mempool.space runs the same open-source esplora backend as
# blockstream.info -- identical API shape (chain_stats.funded_txo_sum /
# spent_txo_sum), different host, separate rate-limit pool. Confirmed
# live: blockstream.info's free tier caps unauthenticated usage at
# 700 requests/hour/IP (a real wall hit during heavy real-world use of
# this tool), and mempool.space returned identical, correct data for a
# real address blockstream.info was rate-limiting at the time. Tried in
# order, not load-balanced -- blockstream.info is the primary host, this
# is a same-day-usable free fallback for exactly the failure mode this
# project just hit, not a general availability strategy.
BALANCE_API_HOSTS = [
    "https://blockstream.info/api/address/{address}",
    "https://mempool.space/api/address/{address}",
]

class BitcoinService(WalletService):
    def check_balance(self, address):
        for url_template in BALANCE_API_HOSTS:
            balance = self._check_one_host(url_template.format(address=address))
            if balance is not None:
                return balance
        return None

    def _check_one_host(self, url):
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            if response.status_code != 200:
                return None
            data = response.json()
            funded = data["chain_stats"]["funded_txo_sum"]
            spent = data["chain_stats"]["spent_txo_sum"]
            return (funded - spent) / 1e8  # Convert satoshis to BTC
        except Exception as e:
            print(f"Error checking Bitcoin balance ({url}): {e}")
            return None