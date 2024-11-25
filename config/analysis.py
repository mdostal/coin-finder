CRYPTO_PATTERNS = {
    "Bitcoin": r"(1[a-km-zA-HJ-NP-Z1-9]{25,34}|bc1[q|p|z][a-zA-HJ-NP-Z0-9]{38,64})",
    "Bitcoin Cash": r"bitcoincash:[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{42}",
    "Bitcoin Gold": r"[AG][a-km-zA-HJ-NP-Z1-9]{26,33}",
    "Cosmos": r"cosmos1[a-z0-9]{38}",
    "Ethereum": r"0x[a-fA-F0-9]{40}",
    "Ethereum Classic": r"0x[a-fA-F0-9]{40}",
    "Dogecoin": r"D{1}[5-9A-HJ-NP-U]{1}[1-9A-HJ-NP-Za-km-z]{32}",
    "Shiba Inu": r"0x[a-fA-F0-9]{40}",
    "Litecoin": r"[LM3][a-km-zA-HJ-NP-Z1-9]{26,33}",
    "Ripple": r"r[1-9A-HJ-NP-Za-km-z]{25,35}",
    "IOTA": r"[A-Z9]{81}",
    "Tether": r"(0x[a-fA-F0-9]{40}|1[a-km-zA-HJ-NP-Z1-9]{25,34})",
    "Helium": r"13[a-zA-Z0-9]{45,48}",
    "Cardano": r"addr[a-z0-9]{58,90}",
    "Zcash": r"t[1-9A-HJ-NP-Za-km-z]{34}",
    "OKCash": r"[0-9A-Za-z]{34}",
    "Binance Coin": r"bnb[a-z0-9]{38}",
    "Monero": r"[48]{1}[0-9AB][1-9A-HJ-NP-Za-km-z]{93}",
}