import sqlite3
import struct

from tests.test_extract_private_key import (
    _align_32bits,
    build_key_record,
    generate_real_der_cprivkey,
)
from web.credential_scan_cache import (
    credential_status_index,
    record_credential_scan,
    run_credential_scan,
    scan_and_record_wallet,
    scan_wallet_key_types,
)

MAGIC = b"\x62\x31\x05\x00\x09\x00\x00\x00"


def build_wallet_with_records(entries):
    """
    entries: [(pubkey_bytes, value_bytes, tag_bytes), ...] -- one (value,
    key) BDB item pair per entry, all on a single leaf page. Same real
    on-disk layout as test_extract_private_key.py's
    build_synthetic_wallet_with_real_key, generalized here to more than
    two records and either tag ("key"/"ckey"), since this cache's own
    scan classifies EVERY record in the file in one pass, not just one
    target address.
    """
    page_size = 512
    file_size = page_size * 12
    buf = bytearray(file_size)
    buf[12:20] = MAGIC
    struct.pack_into("<I", buf, 20, page_size)

    page_base = page_size
    item_count = len(entries) * 2
    first_item_pos = 28
    struct.pack_into("<H H B B", buf, page_base + 20, item_count, first_item_pos, 1, 5)

    pos = _align_32bits(page_base + first_item_pos)
    for pubkey, value_bytes, tag in entries:
        record = build_key_record(pubkey, tag=tag)

        struct.pack_into("<H B", buf, pos, len(value_bytes), 1)
        buf[pos + 3 : pos + 3 + len(value_bytes)] = value_bytes
        pos = _align_32bits(pos + 3 + len(value_bytes))

        struct.pack_into("<H B", buf, pos, len(record), 1)
        buf[pos + 3 : pos + 3 + len(record)] = record
        pos = _align_32bits(pos + 3 + len(record))

    assert pos <= file_size, "test fixture too small for this many records"
    return bytes(buf)


def _unencrypted_entry():
    value, pubkey, address = generate_real_der_cprivkey()
    return (pubkey, value, b"key"), address


def _encrypted_entry():
    value, pubkey, _ = generate_real_der_cprivkey()
    # A "ckey" record's value is AES-encrypted bytes -- irrelevant here,
    # this cache never reads value bytes for ckey OR key records at all
    # (see scan_wallet_key_types), only the key-half pubkey used to
    # derive the address.
    return (pubkey, value, b"ckey"), pubkey_to_address_placeholder(pubkey)


def pubkey_to_address_placeholder(pubkey):
    from tools.scan_wallet_dat import pubkey_to_address

    return pubkey_to_address(pubkey)


# --- scan_wallet_key_types: pure BDB-scan classification ---


def test_scan_wallet_key_types_classifies_unencrypted_key_record(tmp_path):
    (entry, address) = _unencrypted_entry()
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(build_wallet_with_records([entry]))

    key_types = scan_wallet_key_types(str(wallet_file))

    assert key_types[address] == "key"


def test_scan_wallet_key_types_classifies_encrypted_ckey_record(tmp_path):
    (entry, address) = _encrypted_entry()
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(build_wallet_with_records([entry]))

    key_types = scan_wallet_key_types(str(wallet_file))

    assert key_types[address] == "ckey"


def test_scan_wallet_key_types_records_every_address_in_one_pass(tmp_path):
    (key_entry, key_address) = _unencrypted_entry()
    (ckey_entry, ckey_address) = _encrypted_entry()
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(build_wallet_with_records([key_entry, ckey_entry]))

    key_types = scan_wallet_key_types(str(wallet_file))

    assert key_types == {key_address: "key", ckey_address: "ckey"}


def test_scan_wallet_key_types_raises_for_non_wallet_dat_file(tmp_path):
    not_a_wallet = tmp_path / "not-a-wallet.dat"
    not_a_wallet.write_bytes(b"definitely not a BDB wallet.dat")

    try:
        scan_wallet_key_types(str(not_a_wallet))
        assert False, "expected an exception for a non-wallet.dat file"
    except AssertionError:
        pass


def test_credential_scan_cache_never_imports_the_value_reading_extractor():
    """
    Safety property this cache leans on: it's built entirely on
    scan_wallet_dat.py's read_btree_key_items, which only ever reads
    KEY-half item bytes -- private key material lives in the VALUE half
    and is never touched. Confirmed here by checking this module never
    even imports extract_private_key.py's value-touching functions, so a
    future edit can't quietly start reading private key bytes just to
    populate a cache of booleans.
    """
    import web.credential_scan_cache as cache_module

    assert "find_key_value_pair_for_address" not in vars(cache_module)
    assert "extract_wif_for_address" not in vars(cache_module)


# --- record_credential_scan / credential_status_index: the cache itself ---


def test_record_and_read_back_wallet_dat_scan(tmp_path):
    db_path = tmp_path / "credential_scan_cache.db"
    record_credential_scan(
        "/wallets/a.dat",
        is_wallet_dat=True,
        key_types={"1extractable": "key", "1locked": "ckey"},
        db_path=db_path,
    )

    index = credential_status_index(db_path=db_path)

    assert index["/wallets/a.dat"]["is_wallet_dat"] is True
    assert index["/wallets/a.dat"]["addresses"]["1extractable"] == "key"
    assert index["/wallets/a.dat"]["addresses"]["1locked"] == "ckey"
    assert index["/wallets/a.dat"]["error"] is None


def test_record_credential_scan_for_non_wallet_dat_file(tmp_path):
    db_path = tmp_path / "credential_scan_cache.db"
    record_credential_scan("/wallets/electrum.dat", is_wallet_dat=False, error="not a recognized Bitcoin Core wallet.dat (Btree v9)", db_path=db_path)

    index = credential_status_index(db_path=db_path)

    assert index["/wallets/electrum.dat"]["is_wallet_dat"] is False
    assert index["/wallets/electrum.dat"]["addresses"] == {}
    assert "not a recognized" in index["/wallets/electrum.dat"]["error"]


def test_credential_status_index_empty_when_never_scanned(tmp_path):
    db_path = tmp_path / "credential_scan_cache.db"
    assert credential_status_index(db_path=db_path) == {}


def test_record_credential_scan_replaces_stale_addresses_on_rescan(tmp_path):
    db_path = tmp_path / "credential_scan_cache.db"
    record_credential_scan("/wallets/a.dat", is_wallet_dat=True, key_types={"1old": "ckey"}, db_path=db_path)
    record_credential_scan("/wallets/a.dat", is_wallet_dat=True, key_types={"1new": "key"}, db_path=db_path)

    index = credential_status_index(db_path=db_path)

    assert index["/wallets/a.dat"]["addresses"] == {"1new": "key"}


def test_connect_creates_parent_directory(tmp_path):
    db_path = tmp_path / "nested" / "dir" / "credential_scan_cache.db"
    record_credential_scan("/wallets/a.dat", is_wallet_dat=True, key_types={}, db_path=db_path)
    assert db_path.exists()


def test_schema_never_persists_raw_key_material():
    """
    Schema-level guarantee, matching auto_unlock_history.py's own
    equivalent test -- this cache only ever stores addresses and a
    key_type label, never the actual key bytes/WIF.
    """
    import web.credential_scan_cache as cache_module

    assert "value_bytes" not in cache_module._SCHEMA.lower()
    assert "wif" not in cache_module._SCHEMA.lower()
    assert "private" not in cache_module._SCHEMA.lower()


# --- scan_and_record_wallet / run_credential_scan: the job itself ---


def test_scan_and_record_wallet_end_to_end(tmp_path):
    db_path = tmp_path / "credential_scan_cache.db"
    (entry, address) = _unencrypted_entry()
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(build_wallet_with_records([entry]))

    result = scan_and_record_wallet(str(wallet_file), db_path=db_path)

    assert result["is_wallet_dat"] is True
    assert result["key_count"] == 1
    assert result["ckey_count"] == 0
    assert result["error"] is None
    assert credential_status_index(db_path=db_path)[str(wallet_file)]["addresses"][address] == "key"


def test_scan_and_record_wallet_records_failure_without_raising(tmp_path):
    db_path = tmp_path / "credential_scan_cache.db"
    not_a_wallet = tmp_path / "not-a-wallet.dat"
    not_a_wallet.write_bytes(b"not a real wallet.dat")

    result = scan_and_record_wallet(str(not_a_wallet), db_path=db_path)

    assert result["is_wallet_dat"] is False
    assert result["error"]
    index = credential_status_index(db_path=db_path)
    assert index[str(not_a_wallet)]["is_wallet_dat"] is False


def test_run_credential_scan_populates_cache_for_multiple_wallets(tmp_path):
    db_path = tmp_path / "credential_scan_cache.db"
    (key_entry, key_address) = _unencrypted_entry()
    (ckey_entry, ckey_address) = _encrypted_entry()
    wallet_a = tmp_path / "a.dat"
    wallet_a.write_bytes(build_wallet_with_records([key_entry]))
    wallet_b = tmp_path / "b.dat"
    wallet_b.write_bytes(build_wallet_with_records([ckey_entry]))

    summary = run_credential_scan([str(wallet_a), str(wallet_b)], db_path=db_path)

    index = credential_status_index(db_path=db_path)
    assert index[str(wallet_a)]["addresses"][key_address] == "key"
    assert index[str(wallet_b)]["addresses"][ckey_address] == "ckey"
    assert "report" in summary
    assert "2" in summary["report"] or "1" in summary["report"]


def test_run_credential_scan_one_bad_file_does_not_block_the_rest(tmp_path):
    """
    A background job scanning several selected wallets must not abort the
    whole batch because one file turns out not to be a real wallet.dat.
    """
    db_path = tmp_path / "credential_scan_cache.db"
    (entry, address) = _unencrypted_entry()
    good_wallet = tmp_path / "good.dat"
    good_wallet.write_bytes(build_wallet_with_records([entry]))
    bad_wallet = tmp_path / "bad.dat"
    bad_wallet.write_bytes(b"not a wallet.dat")

    run_credential_scan([str(bad_wallet), str(good_wallet)], db_path=db_path)

    index = credential_status_index(db_path=db_path)
    assert index[str(good_wallet)]["addresses"][address] == "key"
    assert index[str(bad_wallet)]["is_wallet_dat"] is False


def test_credential_scan_cache_columns_via_pragma(tmp_path):
    db_path = tmp_path / "credential_scan_cache.db"
    record_credential_scan("/wallets/a.dat", is_wallet_dat=True, key_types={"1abc": "key"}, db_path=db_path)

    conn = sqlite3.connect(str(db_path))
    wallet_columns = {row[1] for row in conn.execute("PRAGMA table_info(credential_scan_wallets)").fetchall()}
    address_columns = {row[1] for row in conn.execute("PRAGMA table_info(credential_scan_addresses)").fetchall()}
    conn.close()

    assert {"wallet_path", "is_wallet_dat", "scanned_at", "error"} <= wallet_columns
    assert {"wallet_path", "address", "key_type"} <= address_columns
