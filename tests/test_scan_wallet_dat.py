import struct
from unittest.mock import MagicMock, patch

from tools.scan_wallet_dat import (
    check_addresses_balances,
    decode_bdb_key_record,
    pubkey_to_address,
    read_btree_key_items,
    scan_wallet_for_addresses,
)

MAGIC = b"\x62\x31\x05\x00\x09\x00\x00\x00"

# Standard public BIP44 test vector (mnemonic "abandon...about"), index 0,
# compressed pubkey -- publicly documented, verified live against bip_utils
# during epic research. Not a real secret.
TEST_VECTOR_PUBKEY_HEX = "03aaeb52dd7494c361049de67cc680e83ebcbbbdbeb13637d92cd845f70308af5e"
TEST_VECTOR_ADDRESS = "1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA"


def compact_size(n):
    assert n < 253
    return bytes([n])


def build_key_record(pubkey_bytes, tag=b"key"):
    return compact_size(len(tag)) + tag + compact_size(len(pubkey_bytes)) + pubkey_bytes


def build_name_record(address):
    address_bytes = address.encode("ascii")
    return compact_size(len(b"name")) + b"name" + compact_size(len(address_bytes)) + address_bytes


def build_synthetic_wallet_bytes():
    """
    Hand-built single-leaf-page BDB btree, matching the exact format
    validated live against the real wallet.dat during epic research:
    header (magic @12, page_size @20), one leaf page (type=5, level=1) with
    two value/key pairs: a "key" record and a "name" record. Value payloads
    are filled with a sentinel (0xEE) never expected to be read.
    """
    page_size = 512
    file_size = 1024
    buf = bytearray(file_size)

    buf[12:20] = MAGIC
    struct.pack_into("<I", buf, 20, page_size)

    page_base = 512
    item_count = 4
    first_item_pos = 28
    btree_level = 1
    page_type = 5
    struct.pack_into("<H H B B", buf, page_base + 20, item_count, first_item_pos, btree_level, page_type)

    pubkey = bytes.fromhex(TEST_VECTOR_PUBKEY_HEX)
    key_record = build_key_record(pubkey)
    name_record = build_name_record(TEST_VECTOR_ADDRESS)

    def align_32bits(i):
        m = i % 4
        return i if m == 0 else i + 4 - m

    pos = align_32bits(page_base + first_item_pos)  # 540

    # item 0: value (sentinel payload -- must never be read)
    value0_len = 10
    struct.pack_into("<H B", buf, pos, value0_len, 1)
    buf[pos + 3 : pos + 3 + value0_len] = b"\xee" * value0_len
    pos = align_32bits(pos + 3 + value0_len)

    # item 1: key -- "key" tag record
    struct.pack_into("<H B", buf, pos, len(key_record), 1)
    buf[pos + 3 : pos + 3 + len(key_record)] = key_record
    key_item_range = (pos + 3, pos + 3 + len(key_record))
    pos = align_32bits(pos + 3 + len(key_record))

    # item 2: value (sentinel payload -- must never be read)
    value2_len = 5
    struct.pack_into("<H B", buf, pos, value2_len, 1)
    buf[pos + 3 : pos + 3 + value2_len] = b"\xee" * value2_len
    value2_range = (pos + 3, pos + 3 + value2_len)
    pos = align_32bits(pos + 3 + value2_len)

    # item 3: key -- "name" tag record
    struct.pack_into("<H B", buf, pos, len(name_record), 1)
    buf[pos + 3 : pos + 3 + len(name_record)] = name_record
    pos = align_32bits(pos + 3 + len(name_record))

    value0_range = (540 + 3, 540 + 3 + value0_len)

    return bytes(buf), key_record, name_record, [value0_range, value2_range]


def test_decode_bdb_key_record_key_tag():
    pubkey = bytes.fromhex(TEST_VECTOR_PUBKEY_HEX)
    record = build_key_record(pubkey)

    decoded = decode_bdb_key_record(record)

    assert decoded == {"type": "key", "pubkey": pubkey}


def test_decode_bdb_key_record_name_tag():
    record = build_name_record(TEST_VECTOR_ADDRESS)

    decoded = decode_bdb_key_record(record)

    assert decoded == {"type": "name", "address": TEST_VECTOR_ADDRESS}


def test_decode_bdb_key_record_unknown_tag_does_not_raise():
    record = compact_size(5) + b"pool\x00"

    decoded = decode_bdb_key_record(record)

    assert decoded["type"] == "pool\x00"


def test_pubkey_to_address_matches_known_test_vector():
    pubkey = bytes.fromhex(TEST_VECTOR_PUBKEY_HEX)

    assert pubkey_to_address(pubkey) == TEST_VECTOR_ADDRESS


def test_read_btree_key_items_extracts_exactly_the_two_key_records_and_never_reads_value_bytes(tmp_path):
    wallet_bytes, key_record, name_record, value_ranges = build_synthetic_wallet_bytes()
    wallet_file = tmp_path / "synthetic.dat"
    wallet_file.write_bytes(wallet_bytes)

    read_ranges = []
    real_open = open

    def tracking_open(*args, **kwargs):
        handle = real_open(*args, **kwargs)
        original_read = handle.read

        def tracking_read(size=-1):
            start = handle.tell()
            data = original_read(size)
            read_ranges.append((start, start + len(data)))
            return data

        handle.read = tracking_read
        return handle

    with patch("builtins.open", tracking_open):
        items = read_btree_key_items(str(wallet_file))

    assert sorted(items) == sorted([key_record, name_record])

    for value_start, value_end in value_ranges:
        for read_start, read_end in read_ranges:
            overlaps = read_start < value_end and read_end > value_start
            assert not overlaps, f"value byte range {(value_start, value_end)} was read at {(read_start, read_end)}"


@patch("tools.scan_wallet_dat.read_btree_key_items")
def test_scan_wallet_for_addresses_deduplicates_and_reports_encrypted_count(mock_read_items):
    pubkey = bytes.fromhex(TEST_VECTOR_PUBKEY_HEX)
    key_record = build_key_record(pubkey)
    ckey_record = build_key_record(pubkey, tag=b"ckey")
    name_record = build_name_record(TEST_VECTOR_ADDRESS)  # same address as derived from pubkey
    mock_read_items.return_value = [key_record, ckey_record, name_record]

    result = scan_wallet_for_addresses("fake-wallet.dat")

    assert result["addresses"] == [{"address": TEST_VECTOR_ADDRESS, "source": "key"}]
    assert result["encrypted_key_count"] == 1


@patch("tools.scan_wallet_dat.load_service_for_coin")
def test_check_addresses_balances_reports_limit_when_applied(mock_load_service):
    fake_service = MagicMock()
    fake_service.check_balance.return_value = 0.0
    mock_load_service.return_value = fake_service

    addresses = [{"address": f"1addr{i}", "source": "key"} for i in range(5)]
    result = check_addresses_balances(addresses, limit=2)

    assert len(result["results"]) == 2
    assert result["limited"] is True
    assert result["total_available"] == 5


@patch("tools.scan_wallet_dat.load_service_for_coin")
def test_check_addresses_balances_reflects_nonzero_balance(mock_load_service):
    fake_service = MagicMock()
    fake_service.check_balance.side_effect = [0.0, 3.5]
    mock_load_service.return_value = fake_service

    addresses = [{"address": "1a", "source": "key"}, {"address": "1b", "source": "name"}]
    result = check_addresses_balances(addresses)

    assert result["results"][1]["balance"] == 3.5
    assert result["limited"] is False
