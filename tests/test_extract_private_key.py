import struct
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from tools.extract_private_key import decode_cprivkey_to_wif, extract_wif_for_address, find_key_value_pair_for_address
from tools.scan_wallet_dat import pubkey_to_address

MAGIC = b"\x62\x31\x05\x00\x09\x00\x00\x00"


def compact_size(n):
    assert n < 253
    return bytes([n])


def build_key_record(pubkey_bytes, tag=b"key"):
    return compact_size(len(tag)) + tag + compact_size(len(pubkey_bytes)) + pubkey_bytes


def _align_32bits(i):
    m = i % 4
    return i if m == 0 else i + 4 - m


def generate_real_der_cprivkey(compressed=True):
    """
    A real secp256k1 keypair, DER-encoded via the `cryptography` library the
    same way OpenSSL's i2d_ECPrivateKey (what Bitcoin Core's CPrivKey uses)
    would, wrapped the way a real "key" record's value is actually
    structured (confirmed against a real wallet.dat during this tool's own
    validation): a compact-size length prefix, then the DER bytes, then
    trailing wallet metadata this tool ignores (represented here by 8
    placeholder bytes -- the real trailer's exact structure doesn't matter
    since decode_cprivkey_to_wif only ever reads the compact-size-declared
    DER length and nothing past it).

    :param compressed: old (2010-era) Bitcoin Core wallets commonly used
        UNCOMPRESSED (65-byte) pubkeys -- both forms are exercised by tests.
    :return: (value_bytes, pubkey_bytes, address)
    """
    private_key = ec.generate_private_key(ec.SECP256K1())
    der_bytes = private_key.private_bytes(Encoding.DER, PrivateFormat.TraditionalOpenSSL, NoEncryption())
    value_bytes = compact_size(len(der_bytes)) + der_bytes + b"\x00" * 8

    numbers = private_key.public_key().public_numbers()
    x = numbers.x.to_bytes(32, "big")
    if compressed:
        prefix = b"\x02" if numbers.y % 2 == 0 else b"\x03"
        pubkey = prefix + x
    else:
        y = numbers.y.to_bytes(32, "big")
        pubkey = b"\x04" + x + y
    address = pubkey_to_address(pubkey)
    return value_bytes, pubkey, address


def build_synthetic_wallet_with_real_key(target_pubkey, target_value_bytes, other_pubkey):
    """
    One leaf page: [value(sentinel), key(other_pubkey)], [value(target DER
    key), key(target_pubkey)] -- two key/value pairs so the "value comes
    immediately before its key" pairing logic has more than one pair to
    disambiguate between.
    """
    page_size = 512
    file_size = 1536
    buf = bytearray(file_size)
    buf[12:20] = MAGIC
    struct.pack_into("<I", buf, 20, page_size)

    page_base = 512
    item_count = 4
    first_item_pos = 28
    struct.pack_into("<H H B B", buf, page_base + 20, item_count, first_item_pos, 1, 5)

    other_record = build_key_record(other_pubkey)
    target_record = build_key_record(target_pubkey)

    pos = _align_32bits(page_base + first_item_pos)

    other_value = b"\xee" * 10
    struct.pack_into("<H B", buf, pos, len(other_value), 1)
    buf[pos + 3 : pos + 3 + len(other_value)] = other_value
    pos = _align_32bits(pos + 3 + len(other_value))

    struct.pack_into("<H B", buf, pos, len(other_record), 1)
    buf[pos + 3 : pos + 3 + len(other_record)] = other_record
    pos = _align_32bits(pos + 3 + len(other_record))

    struct.pack_into("<H B", buf, pos, len(target_value_bytes), 1)
    buf[pos + 3 : pos + 3 + len(target_value_bytes)] = target_value_bytes
    pos = _align_32bits(pos + 3 + len(target_value_bytes))

    struct.pack_into("<H B", buf, pos, len(target_record), 1)
    buf[pos + 3 : pos + 3 + len(target_record)] = target_record
    pos = _align_32bits(pos + 3 + len(target_record))

    return bytes(buf)


def test_decode_cprivkey_to_wif_roundtrips_to_the_same_address():
    value_bytes, pubkey_compressed, expected_address = generate_real_der_cprivkey()

    wif = decode_cprivkey_to_wif(value_bytes, compressed=True)

    from bip_utils import Secp256k1PrivateKey, WifDecoder

    key_bytes, _ = WifDecoder.Decode(wif)
    derived_pubkey = Secp256k1PrivateKey.FromBytes(key_bytes).PublicKey().RawCompressed().ToBytes()
    assert pubkey_to_address(derived_pubkey) == expected_address


def test_find_key_value_pair_for_address_locates_the_correct_pair(tmp_path):
    target_value, target_pubkey, target_address = generate_real_der_cprivkey()
    _, other_pubkey, _ = generate_real_der_cprivkey()

    wallet_bytes = build_synthetic_wallet_with_real_key(target_pubkey, target_value, other_pubkey)
    wallet_file = tmp_path / "synthetic.dat"
    wallet_file.write_bytes(wallet_bytes)

    found = find_key_value_pair_for_address(str(wallet_file), target_address)

    assert found is not None
    assert found["key_type"] == "key"
    assert found["value_bytes"] == target_value


def test_find_key_value_pair_for_address_returns_none_for_unknown_address(tmp_path):
    target_value, target_pubkey, _ = generate_real_der_cprivkey()
    _, other_pubkey, _ = generate_real_der_cprivkey()

    wallet_bytes = build_synthetic_wallet_with_real_key(target_pubkey, target_value, other_pubkey)
    wallet_file = tmp_path / "synthetic.dat"
    wallet_file.write_bytes(wallet_bytes)

    found = find_key_value_pair_for_address(str(wallet_file), "1NotInThisWalletAtAll111111111111")

    assert found is None


@patch("tools.extract_private_key.check_network_status")
def test_extract_wif_for_address_refuses_when_online(mock_status, tmp_path):
    mock_status.return_value = "ONLINE"
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"irrelevant")

    with pytest.raises(RuntimeError, match="OFFLINE"):
        extract_wif_for_address(str(wallet_file), "1anyaddress")


@patch("tools.extract_private_key.check_network_status")
def test_extract_wif_for_address_end_to_end_offline_with_uncompressed_pubkey(mock_status, tmp_path):
    """
    2010-era Bitcoin Core wallets commonly used uncompressed (65-byte)
    pubkeys -- this is the realistic case for this project's actual
    recovery targets, so it must be exercised, not just the modern
    compressed-pubkey default.
    """
    mock_status.return_value = "OFFLINE"
    target_value, target_pubkey, target_address = generate_real_der_cprivkey(compressed=False)
    _, other_pubkey, _ = generate_real_der_cprivkey(compressed=False)
    assert len(target_pubkey) == 65

    wallet_bytes = build_synthetic_wallet_with_real_key(target_pubkey, target_value, other_pubkey)
    wallet_file = tmp_path / "synthetic.dat"
    wallet_file.write_bytes(wallet_bytes)

    wif = extract_wif_for_address(str(wallet_file), target_address)

    from bip_utils import Secp256k1PrivateKey, WifDecoder

    key_bytes, pub_key_mode = WifDecoder.Decode(wif)
    from bip_utils import WifPubKeyModes

    assert pub_key_mode == WifPubKeyModes.UNCOMPRESSED
    derived_pubkey = Secp256k1PrivateKey.FromBytes(key_bytes).PublicKey().RawUncompressed().ToBytes()
    assert pubkey_to_address(derived_pubkey) == target_address


@patch("tools.extract_private_key.check_network_status")
def test_extract_wif_for_address_end_to_end_offline(mock_status, tmp_path):
    mock_status.return_value = "OFFLINE"
    target_value, target_pubkey, target_address = generate_real_der_cprivkey()
    _, other_pubkey, _ = generate_real_der_cprivkey()

    wallet_bytes = build_synthetic_wallet_with_real_key(target_pubkey, target_value, other_pubkey)
    wallet_file = tmp_path / "synthetic.dat"
    wallet_file.write_bytes(wallet_bytes)

    wif = extract_wif_for_address(str(wallet_file), target_address)

    from bip_utils import Secp256k1PrivateKey, WifDecoder

    key_bytes, _ = WifDecoder.Decode(wif)
    derived_pubkey = Secp256k1PrivateKey.FromBytes(key_bytes).PublicKey().RawCompressed().ToBytes()
    assert pubkey_to_address(derived_pubkey) == target_address


@patch("tools.extract_private_key.check_network_status")
def test_extract_wif_for_address_raises_for_unknown_address(mock_status, tmp_path):
    mock_status.return_value = "OFFLINE"
    target_value, target_pubkey, _ = generate_real_der_cprivkey()
    _, other_pubkey, _ = generate_real_der_cprivkey()

    wallet_bytes = build_synthetic_wallet_with_real_key(target_pubkey, target_value, other_pubkey)
    wallet_file = tmp_path / "synthetic.dat"
    wallet_file.write_bytes(wallet_bytes)

    with pytest.raises(RuntimeError, match="not found"):
        extract_wif_for_address(str(wallet_file), "1NotInThisWalletAtAll111111111111")


@patch("tools.extract_private_key.find_key_value_pair_for_address")
@patch("tools.extract_private_key.check_network_status")
def test_extract_wif_for_address_refuses_encrypted_ckey_records(mock_status, mock_find, tmp_path):
    mock_status.return_value = "OFFLINE"
    mock_find.return_value = {"key_type": "ckey", "value_bytes": b"encrypted-blob", "pubkey_len": 33}
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"irrelevant")

    with pytest.raises(RuntimeError, match="ENCRYPTED"):
        extract_wif_for_address(str(wallet_file), "1anyaddress")
