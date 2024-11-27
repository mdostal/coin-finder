WALLET_EXTENSIONS = ['.dat', '.key', '.wallet', '.json', '.backup']
COIN_NAMES = ['helium', 'iota', 'ripple', 'tether', 'shiba', 'zcash', 'btc',
               'bitcoin', 'bitcoin_cash', 'bitcoin_gold', 'cardano', 'cosmos',
                 'diamond_coin', 'digibyte', 'dogecoin', 'ethereum', 'ethereum_classic',
                   'litecoin', 'monero', 'okcash', 'ripple', 'xrp', 'dmd', 'diamond', 
                   'iota', 'miota', 'eth', 'etc', 'ltc', 'xmr', 'btg', 'bch', 'bsv', 'dash', 'doge', 'ltc', 'xlm', 'zec']
WALLET_KEYWORDS = ['wallet', 'crypto', 'bitcoin', 'ethereum', 'backup']

MAX_FILE_SIZE = 45 * 1024 * 1024  # 44 MB   bumped to 45 MB for helium which often hits that -- sadly helium hits many of them -- tempted to run without helum
MIN_FILE_SIZE = 1  # 1 byte (to exclude empty files)
