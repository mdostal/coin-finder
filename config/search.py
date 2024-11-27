WALLET_EXTENSIONS = ['.dat', '.key', '.wallet', '.json', '.backup']
COIN_NAMES = ['helium', 'iota', 'ripple', 'tether', 'shiba', 'zcash', 'btc',
               'bitcoin', 'bitcoin_cash', 'bitcoin_gold', 'cardano', 'cosmos',
                 'diamond_coin', 'digibyte', 'dogecoin', 'ethereum', 'ethereum_classic',
                   'litecoin', 'monero', 'okcash', 'ripple', 'xrp', 'dmd', 'diamond', 
                   'iota', 'miota', 'eth', 'etc', 'ltc', 'xmr', 'btg', 'bch', 'bsv', 'dash', 'doge', 'ltc', 'xlm', 'zec']
WALLET_KEYWORDS = ['wallet', 'crypto', 'bitcoin', 'ethereum', 'backup']+ COIN_NAMES

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MIN_FILE_SIZE = 1  # 1 byte (to exclude empty files)
