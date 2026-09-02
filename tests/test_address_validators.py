"""Tests for config/address_validators.py -- the offline checksum filter
that stops shape-only regex matches (CRYPTO_PATTERNS) from being trusted
as real addresses.

Every "Group 1" real-address fixture below is a genuine, published address
pulled from the coin's own documentation or a public block explorer (never
fabricated) -- see the source comment next to each one. False negatives
(a validator rejecting a real address) are the danger this module exists
to avoid, so every Group 1 fixture is exercised three ways: the real
address must pass, a single-character-corrupted copy of it must fail
(proving the checksum is actually being checked, not just the shape), and
-- wherever a real garbage string from tonight's bug report happens to
match that coin's CRYPTO_PATTERNS shape -- that garbage must fail too.
"""

import re

import pytest

from config.address_validators import ADDRESS_VALIDATORS, filter_valid_addresses
from config.analysis import CRYPTO_PATTERNS

# Tonight's real garbage: Rust mangled-symbol strings from a prior scan's
# own output file, re-scanned as if it were wallet content.
GARBAGE_DIGIBYTE_AND_DIAMOND = "d6thread6Thread5cname17hd86fb86E"
GARBAGE_DIGIBYTE_ONLY = "df29a6dde7b3e33ab57f416f11"

# Group 1: real, published example addresses. Source noted per entry.
REAL_ADDRESSES = {
    # Reused from tests/test_analyze_wallets.py's existing fixture.
    "Bitcoin": "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2",
    # btgexplorer.com (Bitcoin Gold block explorer) address page.
    "Bitcoin Gold": "GTNjvCGssb2rbLnDV1xxsHmunQdvXnY2Ft",
    # chainz.cryptoid.info/dgb/ (DigiByte block explorer) address page.
    "Digibyte": "DN4yzowAzPbtM6Hh4HsNjFH8QjurZ4Nzhz",
    # coinlore.com/coin/diamond/richlist -- DMD Diamond (v3/classic,
    # base58check) rich-list top holder address.
    "Diamond Coin": "dFrqNGxc65eWngmok2z6i1gewzpRAuzfoq",
    # blockchair.com/litecoin/address/... -- real on-chain Litecoin address.
    "Litecoin": "LeBFQzwaE8TnEXDWNUqtuTgX8xVdKhsGXC",
    # A real Dogecoin Foundation "Bronze The Doge" fundraising address.
    "Dogecoin": "D8HjKf37rF3Ho7tjwe17MPN8xQ2UbHSUhB",
    # Zcash's own historical Founders' Reward address (protocol-level,
    # documented in zcash/zcash PR #1398 and the Zcash protocol spec).
    "Zcash": "t3Vz22vK5z2LcKEdg16Yv4FFneEL1zg9ojd",
    # omniexplorer.info -- a real Tether Omni-layer treasury address
    # (Omni rides on ordinary Bitcoin base58check addresses).
    "Tether": "1NTMakcgVwQpMdGxRQnFKyb3G1FAJysSfz",
    # xrpl.org's own "Basic Data Types" documentation example address.
    "Ripple": "r9cZA1mLK5R5Am25ArfXFmqgNwjZgnfk59",
    # getmonero.org/resources -- the Monero project's own CCS donation
    # address.
    "Monero": "46BeWrHpwXmHDpDEUmZBWZfoQpdc6HaERCNmx1pEYL2rAcuwufPN9rXHHtyUA4QVy66qeFQkn6sfK8aHYjA3jk3o1Bv16em",
    # The existing Bitcoin fixture above, translated to Bitcoin Cash's
    # cashaddr format (published by Blockchain.com in "A New Look for
    # Bitcoin Cash Addresses").
    "Bitcoin Cash": "bitcoincash:qpm2qsznhks23z7629mms6s4cwef74vcwvy22gdx6a",
    # Cardano's own CIP-19 ("Cardano Addresses") specification, Type-00
    # mainnet base-address example.
    "Cardano": "addr1qx2fxv2umyhttkxyxp8x0dlpdt3k6cwng5pxj3jhsydzer3n0d3vllmyqwsx5wktcd8cc3sq835lu7drv2xwl2wywfgse35a3x",
    # A real Cosmos Hub validator's account address (Staking Facilities).
    "Cosmos": "cosmos1x88j7vp2xnw3zec8ur3g4waxycyz7m0mcreeaj",
    # helium/devdocs (Helium's own developer docs repo on GitHub),
    # blockchain-cli.md example address.
    "Helium": "13QvnWtjpi3HYoBPpcEmqansMyCbJSkRpSthXAJFTaxwUraKKaP",
}

# Real, historically-used Ethereum-family ("0x" + 40 hex) addresses, both
# EIP-55-checksummed (mixed case) and all-lowercase/unchecksummed, to prove
# _validate_eth_shape_statistical (config/address_validators.py) doesn't
# over-reject real addresses -- the single most important guarantee in this
# module per esf-01's own risk notes.
REAL_ETH_ADDRESSES = {
    # Vitalik Buterin's public, ENS-linked (vitalik.eth) address --
    # widely published, e.g. on Etherscan.
    "vitalik_checksummed": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
    "vitalik_lowercase": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
    # The Ethereum Foundation's original (Frontier-era) donation address,
    # documented across Ethereum Foundation blog posts and Etherscan.
    "ethereum_foundation_checksummed": "0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe",
    "ethereum_foundation_lowercase": "0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae",
    # Tether's own USDT ERC-20 contract address on Ethereum mainnet --
    # published by Tether/Etherscan, and itself a real "0x"+40-hex address
    # (contract addresses are ordinary 20-byte addresses).
    "usdt_contract_checksummed": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
}

GROUP_2_PASS_THROUGH_COINS = ["IOTA"]
ETH_SHAPE_STATISTICAL_COINS = ["Ethereum", "Ethereum Classic", "Shiba Inu"]

# Real, live examples that cost an API call before this story existed --
# see .pHive/epics/eth-shape-statistical-filter/stories/esf-01-*.yaml.
NEAR_NULL_PLACEHOLDER = "0x0000000000000000000000000000000000000042"
ASCII_ENCODED_TEXT = "0x606563686f2022553246736447566b58312b5a53"
CANONICAL_NULL_ADDRESS = "0x0000000000000000000000000000000000000000"


def _corrupt(address: str) -> str:
    """Flip a single character near the middle of the address's payload
    (well past any fixed prefix like "bitcoincash:" or "addr1") to a
    different character, to prove checksum validation -- not just shape --
    is what's rejecting it."""
    mid = len(address) // 2
    original = address[mid]
    replacement = "9" if original != "9" else "8"
    corrupted = address[:mid] + replacement + address[mid + 1:]
    assert corrupted != address
    return corrupted


@pytest.mark.parametrize("coin", REAL_ADDRESSES.keys())
def test_real_group1_address_passes_validation(coin):
    validate = ADDRESS_VALIDATORS[coin]
    assert validate(REAL_ADDRESSES[coin]) is True


@pytest.mark.parametrize("coin", REAL_ADDRESSES.keys())
def test_corrupted_group1_address_fails_validation(coin):
    validate = ADDRESS_VALIDATORS[coin]
    assert validate(_corrupt(REAL_ADDRESSES[coin])) is False


@pytest.mark.parametrize("coin", ["Digibyte", "Diamond Coin"])
def test_garbage_string_fails_where_shape_matches(coin):
    # Confirm the premise first: this garbage really does match the shape
    # regex today (that's the bug) before proving the validator catches it.
    assert re.fullmatch(CRYPTO_PATTERNS[coin], GARBAGE_DIGIBYTE_AND_DIAMOND)
    assert ADDRESS_VALIDATORS[coin](GARBAGE_DIGIBYTE_AND_DIAMOND) is False


def test_second_garbage_string_fails_for_digibyte():
    assert re.fullmatch(CRYPTO_PATTERNS["Digibyte"], GARBAGE_DIGIBYTE_ONLY)
    assert ADDRESS_VALIDATORS["Digibyte"](GARBAGE_DIGIBYTE_ONLY) is False


def test_every_crypto_pattern_coin_has_a_validator_entry():
    """No coin may be silently dropped from the mapping -- Group 2/3 coins
    get an explicit pass-through, not an omission."""
    missing = set(CRYPTO_PATTERNS) - set(ADDRESS_VALIDATORS)
    assert missing == set()


@pytest.mark.parametrize("coin", GROUP_2_PASS_THROUGH_COINS)
def test_group2_coins_pass_through_even_garbage_shapes(coin):
    validate = ADDRESS_VALIDATORS[coin]
    assert validate("0x" + "a" * 40) is True
    assert validate("totally not a real address but shape matched") is True


# --- esf-01: statistical filter for the "0x" + 40 hex shape -----------------
#
# Ethereum, Ethereum Classic, and Shiba Inu (plus Tether's ERC-20 branch,
# tested separately below) are no longer bare pass-through: they still never
# require EIP-55 checksumming (see the real-address tests below), but they do
# reject the two categories of shape documented on
# _validate_eth_shape_statistical -- near-null/placeholder byte patterns and
# addresses whose bytes secretly decode to printable ASCII text.


@pytest.mark.parametrize("coin", ETH_SHAPE_STATISTICAL_COINS)
@pytest.mark.parametrize(
    "implausible_address",
    [NEAR_NULL_PLACEHOLDER, ASCII_ENCODED_TEXT, CANONICAL_NULL_ADDRESS],
)
def test_eth_shape_statistical_filter_rejects_implausible_matches(coin, implausible_address):
    # Confirm the premise first: these really do match the shape regex
    # today (that's the bug) before proving the validator catches them.
    assert re.fullmatch(CRYPTO_PATTERNS[coin], implausible_address)
    assert ADDRESS_VALIDATORS[coin](implausible_address) is False


@pytest.mark.parametrize("coin", ETH_SHAPE_STATISTICAL_COINS + ["Tether"])
@pytest.mark.parametrize("real_address", REAL_ETH_ADDRESSES.values(), ids=REAL_ETH_ADDRESSES.keys())
def test_eth_shape_statistical_filter_accepts_real_addresses(coin, real_address):
    # The single most important test in this module per esf-01's own risk
    # notes: real, historically-used addresses -- checksummed AND
    # all-lowercase/unchecksummed -- must never be rejected.
    assert re.fullmatch(CRYPTO_PATTERNS[coin], real_address)
    assert ADDRESS_VALIDATORS[coin](real_address) is True


@pytest.mark.parametrize("coin", ETH_SHAPE_STATISTICAL_COINS + ["Tether"])
def test_eth_shape_statistical_filter_does_not_overreject_a_couple_of_zero_bytes(coin):
    # A normal/random-ish byte distribution that happens to contain a
    # couple of zero bytes (well under the "fewer than 3 non-zero bytes"
    # near-null threshold) must still be accepted -- the filter must not
    # be more aggressive than its documented, deliberately extreme
    # thresholds.
    payload = bytes([0x00, 0x00] + list(range(1, 19)))  # 2 zero, 18 non-zero
    assert len(payload) == 20
    address = "0x" + payload.hex()
    assert re.fullmatch(CRYPTO_PATTERNS[coin], address)
    assert ADDRESS_VALIDATORS[coin](address) is True


def test_binance_coin_pass_through_documented_gap():
    # bip_utils has no BnbAddr* decoder -- documented follow-up, not a fix
    # attempted here.
    assert ADDRESS_VALIDATORS["Binance Coin"]("bnb1anything") is True


def test_tether_erc20_branch_still_never_requires_eip55_checksumming():
    # Tether's regex also matches plain "0x" + 40 hex (ERC-20 branch). This
    # is a normal/random-ish (non-implausible) address, so the statistical
    # filter it's now routed through (_validate_eth_shape_statistical) must
    # still accept it unchecksummed -- EIP-55 is never required.
    assert ADDRESS_VALIDATORS["Tether"]("0x" + "a" * 40) is True


def test_tether_omni_branch_uses_real_base58check():
    # esf-01: Tether's base58/Omni branch must be completely unaffected by
    # the new "0x" branch statistical filter -- these assertions predate
    # esf-01 and are unmodified by it.
    validate = ADDRESS_VALIDATORS["Tether"]
    assert validate(REAL_ADDRESSES["Tether"]) is True
    assert validate(_corrupt(REAL_ADDRESSES["Tether"])) is False


def test_tether_omni_branch_unaffected_by_eth_shape_implausible_matches():
    # esf-01: the near-null/ASCII-text rejections added for the "0x" branch
    # must never leak into the base58/Omni branch's own (unrelated)
    # checksum logic -- a base58 string is never dispatched through
    # _validate_eth_shape_statistical in the first place.
    validate = ADDRESS_VALIDATORS["Tether"]
    assert not REAL_ADDRESSES["Tether"].startswith(("0x", "0X"))
    assert validate(REAL_ADDRESSES["Tether"]) is True


def test_filter_valid_addresses_drops_only_implausible_eth_shape_matches():
    # esf-01 acceptance criterion: filter_valid_addresses() end-to-end for
    # Ethereum/Ethereum Classic/Shiba Inu/Tether, given a mix of real-shaped
    # and implausible addresses, drops only the implausible ones.
    real = REAL_ETH_ADDRESSES["vitalik_checksummed"]
    real_lowercase = REAL_ETH_ADDRESSES["vitalik_lowercase"]
    mixed = [real, NEAR_NULL_PLACEHOLDER, real_lowercase, ASCII_ENCODED_TEXT, CANONICAL_NULL_ADDRESS]
    for coin in ETH_SHAPE_STATISTICAL_COINS + ["Tether"]:
        assert filter_valid_addresses(coin, mixed) == [real, real_lowercase]


def test_filter_valid_addresses_leaves_tether_omni_branch_untouched():
    # Same end-to-end entry point, proving the base58/Omni branch mixed in
    # alongside "0x"-shaped matches is filtered by its own real checksum
    # logic, not swept up by the eth-shape statistical filter.
    mixed = [REAL_ADDRESSES["Tether"], NEAR_NULL_PLACEHOLDER, _corrupt(REAL_ADDRESSES["Tether"])]
    assert filter_valid_addresses("Tether", mixed) == [REAL_ADDRESSES["Tether"]]


def test_okcash_regex_no_longer_accepts_non_base58_alphabet_chars():
    # Old shapeless regex accepted 0, O, I, l (not part of any base58
    # alphabet); the tightened regex must reject them.
    pattern = CRYPTO_PATTERNS["OKCash"]
    assert re.fullmatch(pattern, "0" * 34) is None
    assert re.fullmatch(pattern, "O" * 34) is None
    assert re.fullmatch(pattern, "I" * 34) is None
    assert re.fullmatch(pattern, "l" * 34) is None


def test_bitcoin_bech32_segwit_address_does_not_false_negative():
    # CRYPTO_PATTERNS's own Bitcoin regex has a "bc1..." bech32 branch
    # (native SegWit) in addition to legacy base58check. These are BIP-173
    # / BIP-350's own published test vectors -- real, valid encodings --
    # covering P2WPKH, P2WSH, and P2TR (Taproot) so none of the three
    # common SegWit address shapes false-negative.
    validate = ADDRESS_VALIDATORS["Bitcoin"]
    segwit_addrs = [
        "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",  # P2WPKH
        "bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3",  # P2WSH
        "bc1p5d7rjq7g6rdk2yhzks9smlaqtedr4dekq08ge8ztwac72sfr9rusxg3297",  # P2TR / Taproot
    ]
    for addr in segwit_addrs:
        assert validate(addr) is True
        assert validate(_corrupt(addr)) is False


def test_cardano_enterprise_address_does_not_false_negative():
    # Cardano's own CIP-19 spec Type-06 (Enterprise) mainnet example --
    # AdaShelleyAddrDecoder alone rejects this in the installed bip_utils
    # version (it hard-codes base-address length), which would have been
    # a false negative on a common, completely legitimate address
    # subtype. The validator must fall back to a generic bech32 checksum
    # check to accept it.
    validate = ADDRESS_VALIDATORS["Cardano"]
    enterprise_addr = "addr1vx2fxv2umyhttkxyxp8x0dlpdt3k6cwng5pxj3jhsydzers66hrl8"
    assert validate(enterprise_addr) is True
    assert validate(_corrupt(enterprise_addr)) is False


def test_okcash_validator_shares_the_generic_base58check_filter():
    # OKCash has no per-coin real-address-fixture requirement in the story
    # AC (only the regex tightening + shared generic filter) -- reuse the
    # real Bitcoin fixture to prove the shared filter accepts a
    # well-formed checksummed base58 string and rejects garbage.
    validate = ADDRESS_VALIDATORS["OKCash"]
    assert validate(REAL_ADDRESSES["Bitcoin"]) is True
    assert validate(GARBAGE_DIGIBYTE_AND_DIAMOND) is False
