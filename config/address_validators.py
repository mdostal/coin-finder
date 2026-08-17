"""Offline, checksum-based address validators for config.analysis.CRYPTO_PATTERNS.

CRYPTO_PATTERNS is pure shape matching -- a regex alternation with zero
coin-specific structural or checksum verification. That is what let Rust
mangled-symbol strings (e.g. "d6thread6Thread5cname17hd86fb86E") get
recorded as candidate Digibyte addresses: the string happened to have the
right length and alphabet, nothing more.

ADDRESS_VALIDATORS below maps every CRYPTO_PATTERNS coin name to a
``validate(address: str) -> bool`` function that re-checks a regex match
against the coin's real, offline-verifiable checksum wherever one exists,
built entirely on bip_utils (already an installed project dependency --
see requirements.txt). Every coin is honestly categorized:

- "Group 1" (real checksum, verifiable offline): standard base58check
  coins (Bitcoin, Bitcoin Gold, Digibyte, Diamond Coin, Litecoin,
  Dogecoin, Zcash, Tether's base58/Omni branch, OKCash) via
  Base58Decoder.CheckDecode; Ripple via its own base58 alphabet; Monero
  via its Keccak-checksummed address decoder; Bitcoin Cash via cashaddr;
  Cardano via its Shelley/Byron address decoders; Cosmos via its bech32
  address decoder.
- "Group 2/3" (no offline-verifiable checksum, or the tooling for one
  isn't installed): an explicit, documented pass-through validator that
  always returns True. These are NOT silently omitted -- every
  CRYPTO_PATTERNS key must resolve to an entry here so callers can apply
  the mapping uniformly without a coin-by-coin conditional.

False negatives (rejecting a real address) are strictly worse than the
bug being fixed here, since this tool's entire purpose is not missing a
real wallet -- see the false-negative risk notes on each validator below.
"""

from bip_utils import (
    AdaByronAddrDecoder,
    AdaShelleyAddrDecoder,
    AtomAddrDecoder,
    Base58Alphabets,
    Base58Decoder,
    Bech32Decoder,
    BchP2PKHAddrDecoder,
    BchP2SHAddrDecoder,
    SegwitBech32Decoder,
    XmrAddrDecoder,
)

# Bitcoin Cash cashaddr net-version bytes (mainnet, hrp "bitcoincash") for
# the two address kinds a real address can be -- pay-to-pubkey-hash and
# pay-to-script-hash. Not exposed as a named constant anywhere in bip_utils
# for the plain (non-BIP44) decoder path, so pinned here per the cashaddr
# spec (https://github.com/bitcoincashorg/bitcoincash.org/blob/master/spec/cashaddr.md).
_BCH_HRP = "bitcoincash"
_BCH_NET_VER_P2PKH = b"\x00"
_BCH_NET_VER_P2SH = b"\x08"

# Monero mainnet net-version bytes: standard, integrated, and subaddress.
# CRYPTO_PATTERNS's Monero shape regex (`[48][0-9AB]...`) matches both
# standard/integrated addresses (leading "4") and subaddresses (leading
# "8"), so a validator that only accepted the standard net-version would
# false-negative on real subaddresses.
_XMR_NET_VER_STANDARD = b"\x12"
_XMR_NET_VER_INTEGRATED = b"\x13"
_XMR_NET_VER_SUBADDRESS = b"\x2a"


def _pass_through(_address: str) -> bool:
    """Always-true validator for coins with no offline-verifiable checksum
    (or no already-installed decoder for the checksum that does exist).

    Used for:
    - Ethereum, Ethereum Classic, Shiba Inu ("0x" + 40 hex): EIP-55 mixed-
      case checksumming exists but is optional -- real addresses in the
      wild are routinely all-lowercase/unchecksummed, so enforcing it
      would reject genuine addresses (a false-negative regression, not a
      fix).
    - IOTA ([A-Z9]{81}): the real IOTA checksum is a separate 9-tryte
      suffix the current regex doesn't even capture, and trytes aren't a
      bip_utils (or any other already-installed) alphabet.
    - Binance Coin (bnb...): BNB Beacon Chain addresses are bech32 and
      checksummed at the protocol level, but bip_utils has no BnbAddr*
      decoder. Closing this needs a new dependency -- out of scope here,
      flagged as a follow-up.
    """
    return True


def _validate_base58check_bitcoin_alphabet(address: str) -> bool:
    """Generic base58check round-trip using the standard (Bitcoin) alphabet.

    Used for every Group 1 coin that is a Bitcoin-style base58check
    address: Bitcoin, Bitcoin Gold, Digibyte, Diamond Coin, Litecoin,
    Dogecoin, Zcash, and OKCash. Deliberately does NOT check each coin's
    exact version byte -- Base58Decoder.CheckDecode only requires the
    string to decode and its 4-byte checksum to verify, which a random
    shape-only match essentially never does by chance, while still
    accepting every real address regardless of which of a coin's several
    valid version bytes (P2PKH vs. P2SH, mainnet variants, etc.) it uses.
    """
    try:
        Base58Decoder.CheckDecode(address)
        return True
    except Exception:
        return False


def _validate_bitcoin(address: str) -> bool:
    """Bitcoin specifically (as opposed to the other base58check coins
    below): CRYPTO_PATTERNS's own Bitcoin regex has two branches --
    legacy base58check ("1...") AND native SegWit bech32 ("bc1...",
    covering P2WPKH, P2WSH, and P2TR/Taproot -- the majority format for
    addresses generated by modern wallets). A validator that only checked
    base58check would reject every real bc1 address matched by that same
    regex, a real false-negative regression on very common addresses.
    Tries base58check first, then falls back to a generic SegWit bech32
    checksum decode (any witness version, so Taproot isn't excluded
    either) before giving up.
    """
    if _validate_base58check_bitcoin_alphabet(address):
        return True
    try:
        SegwitBech32Decoder.Decode("bc", address)
        return True
    except Exception:
        return False


def _validate_tether(address: str) -> bool:
    """Tether's CRYPTO_PATTERNS shape covers two unrelated address formats
    in one regex alternation: an ERC-20-style "0x" + 40 hex branch, and a
    base58/Omni-layer branch (Tether-on-Bitcoin). They need different
    validators, not one:

    - The "0x" branch is exactly Ethereum's address shape, so it gets the
      same documented pass-through as the rest of the ETH family (see
      _pass_through) -- EIP-55 is optional, so enforcing it would reject
      real unchecksummed Tether ERC-20 addresses.
    - The base58/Omni branch is a real Bitcoin-alphabet base58check
      address (Omni Layer rides on ordinary Bitcoin addresses), so it
      gets the real checksum filter.
    """
    if address.startswith(("0x", "0X")):
        return True
    return _validate_base58check_bitcoin_alphabet(address)


def _validate_ripple(address: str) -> bool:
    """Ripple uses its own base58 alphabet (still base58check underneath)."""
    try:
        Base58Decoder.CheckDecode(address, Base58Alphabets.RIPPLE)
        return True
    except Exception:
        return False


def _validate_monero(address: str) -> bool:
    """Monero's own Keccak-256-checksummed base58 variant.

    Tries every mainnet net-version byte the shape regex could plausibly
    match (see _XMR_NET_VER_* above) so a real subaddress or integrated
    address doesn't false-negative just because it isn't a standard
    address.
    """
    for net_ver in (_XMR_NET_VER_STANDARD, _XMR_NET_VER_INTEGRATED, _XMR_NET_VER_SUBADDRESS):
        try:
            XmrAddrDecoder.DecodeAddr(address, net_ver=net_ver)
            return True
        except Exception:
            continue
    return False


def _validate_bitcoin_cash(address: str) -> bool:
    """Bitcoin Cash cashaddr, tried as both P2PKH and P2SH -- a real
    address is legitimately one or the other, so only rejecting when
    neither decodes avoids false-negatives on real P2SH addresses.
    """
    for decoder, net_ver in (
        (BchP2PKHAddrDecoder, _BCH_NET_VER_P2PKH),
        (BchP2SHAddrDecoder, _BCH_NET_VER_P2SH),
    ):
        try:
            decoder.DecodeAddr(address, hrp=_BCH_HRP, net_ver=net_ver)
            return True
        except Exception:
            continue
    return False


def _validate_cardano(address: str) -> bool:
    """Cardano Shelley-era ("addr1...") or legacy Byron-era address.

    Tries AdaShelleyAddrDecoder first -- the decoder named in the design
    discussion, which strictly validates the most common Shelley address
    subtype (a "base" address: payment key hash + staking key hash).
    IMPORTANT: in the installed bip_utils version (2.12.1), that decoder
    hard-codes the base-address length and rejects every other real,
    legitimate Shelley address subtype -- enterprise addresses (payment
    only, e.g. many exchange deposit addresses, per Cardano's own CIP-19
    spec), pointer, and script addresses all fail it with a length
    mismatch even though they are completely valid addresses. Confirmed
    directly: CIP-19's own enterprise-address example
    ("addr1vx2fxv2umyhttkxyxp8x0dlpdt3k6cwng5pxj3jhsydzers66hrl8") raises
    ValueError("Invalid length (expected 57, got 29)") from
    AdaShelleyAddrDecoder alone -- a real false negative this fallback
    exists to close.

    So on failure, falls back to the same bech32 checksum decode
    AdaShelleyAddrDecoder itself uses internally (Bech32Decoder.Decode
    with hrp "addr"), which validates the real bech32 checksum without
    assuming a specific payload length/structure -- covering every
    Shelley address subtype the same way Base58Decoder.CheckDecode
    covers every base58check coin's version bytes above. Finally falls
    back to AdaByronAddrDecoder so a real legacy-era address isn't
    rejected either.
    """
    try:
        AdaShelleyAddrDecoder.DecodeAddr(address)
        return True
    except Exception:
        pass
    try:
        Bech32Decoder.Decode("addr", address)
        return True
    except Exception:
        pass
    try:
        AdaByronAddrDecoder.DecodeAddr(address)
        return True
    except Exception:
        return False


def _validate_cosmos(address: str) -> bool:
    """Cosmos Hub bech32 address (hrp "cosmos")."""
    try:
        AtomAddrDecoder.DecodeAddr(address, hrp="cosmos")
        return True
    except Exception:
        return False


ADDRESS_VALIDATORS = {
    # Group 1: real, offline-verifiable checksum.
    "Bitcoin": _validate_bitcoin,
    "Bitcoin Gold": _validate_base58check_bitcoin_alphabet,
    "Digibyte": _validate_base58check_bitcoin_alphabet,
    "Diamond Coin": _validate_base58check_bitcoin_alphabet,
    "Litecoin": _validate_base58check_bitcoin_alphabet,
    "Dogecoin": _validate_base58check_bitcoin_alphabet,
    "Zcash": _validate_base58check_bitcoin_alphabet,
    "Tether": _validate_tether,
    "Ripple": _validate_ripple,
    "Monero": _validate_monero,
    "Bitcoin Cash": _validate_bitcoin_cash,
    "Cardano": _validate_cardano,
    "Cosmos": _validate_cosmos,
    "Helium": _validate_base58check_bitcoin_alphabet,
    # OKCash: same generic base58check filter as the coins above (see
    # config/analysis.py's tightened OKCash regex) -- doesn't need
    # OKCash's exact version byte, only a valid base58check round-trip.
    "OKCash": _validate_base58check_bitcoin_alphabet,
    # Group 2/3: documented pass-through, not a silent omission.
    "Ethereum": _pass_through,
    "Ethereum Classic": _pass_through,
    "Shiba Inu": _pass_through,
    "IOTA": _pass_through,
    "Binance Coin": _pass_through,
}


def filter_valid_addresses(coin, matches):
    """The one shared filter both CRYPTO_PATTERNS call sites
    (tools/analyze_wallets.py's analyze_wallet_file() and
    tools/scan_gmail.py's find_addresses_in_payload()) must use -- keeps
    the filtering logic in exactly one place instead of each call site
    reimplementing the ADDRESS_VALIDATORS lookup independently.

    :param coin: a CRYPTO_PATTERNS key.
    :param matches: iterable of raw regex matches for that coin.
    :return: list of matches whose coin validator returned True. A coin
        missing from ADDRESS_VALIDATORS (should not happen -- see
        test_every_crypto_pattern_coin_has_a_validator_entry) falls back
        to the documented pass-through rather than silently dropping
        every match for that coin.
    """
    validator = ADDRESS_VALIDATORS.get(coin, _pass_through)
    return [match for match in matches if validator(match)]
