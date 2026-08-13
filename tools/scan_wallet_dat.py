import os
import struct
import sys
from pathlib import Path

from bip_utils import P2PKHAddrEncoder

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.bitcoin import BitcoinService
from tools.check_wallet_balances import _check_balance_with_retries

EXPECTED_MAGIC = b"\x62\x31\x05\x00\x09\x00\x00\x00"

SERVICES_BY_COIN = {
    "Bitcoin": BitcoinService,
}


def _align_32bits(i):
    m = i % 4
    return i if m == 0 else i + 4 - m


def _read_compact_size(data, offset):
    """Bitcoin Core's WriteCompactSize format (only the 1-byte case is
    needed here -- tags and pubkey/address lengths are always small)."""
    n = data[offset]
    if n < 253:
        return n, offset + 1
    elif n == 253:
        return struct.unpack_from("<H", data, offset + 1)[0], offset + 3
    elif n == 254:
        return struct.unpack_from("<I", data, offset + 1)[0], offset + 5
    else:
        return struct.unpack_from("<Q", data, offset + 1)[0], offset + 9


def decode_bdb_key_record(key_bytes):
    """
    Decode a Bitcoin Core BDB key record's CDataStream tag + payload.
    "key"/"ckey" -> {"type": tag, "pubkey": bytes}. "name" ->
    {"type": "name", "address": str}. Anything else -> {"type": tag}
    (counted by callers, not deep-parsed).
    """
    tag_len, offset = _read_compact_size(key_bytes, 0)
    tag = key_bytes[offset : offset + tag_len].decode("ascii", errors="replace")
    offset += tag_len

    if tag in ("key", "ckey"):
        pk_len, offset = _read_compact_size(key_bytes, offset)
        pubkey = key_bytes[offset : offset + pk_len]
        return {"type": tag, "pubkey": pubkey}

    if tag == "name":
        addr_len, offset = _read_compact_size(key_bytes, offset)
        address = key_bytes[offset : offset + addr_len].decode("ascii", errors="replace")
        return {"type": "name", "address": address}

    return {"type": tag}


def pubkey_to_address(pubkey_bytes):
    """P2PKH address from a raw (compressed or uncompressed) pubkey, via the
    audited bip_utils encoder -- no hand-rolled hashing/base58."""
    return P2PKHAddrEncoder.EncodeKey(pubkey_bytes, net_ver=b"\x00")


def read_btree_key_items(wallet_path):
    """
    Walk a Bitcoin Core wallet.dat's BDB btree leaf pages, returning the raw
    KEY-half bytes of every non-deleted item. SAFETY-CRITICAL: value-half
    file positions are skipped via their length header alone -- never
    .read() -- so private-key bytes (stored in the value half of "key"/
    "ckey" records) are never loaded into memory during this walk. Every
    address this tool needs lives in the key half (pubkey for key/ckey
    records, address string for name records).
    """
    key_items = []

    with open(wallet_path, "rb") as wallet_file:
        wallet_file.seek(12)
        assert wallet_file.read(8) == EXPECTED_MAGIC, "not a recognized Bitcoin Core wallet.dat (Btree v9)"

        wallet_file.seek(20)
        page_size = struct.unpack("<I", wallet_file.read(4))[0]
        wallet_file_size = os.path.getsize(wallet_path)

        for page_base in range(page_size, wallet_file_size, page_size):
            wallet_file.seek(page_base + 20)
            header = wallet_file.read(6)
            if len(header) < 6:
                continue
            item_count, first_item_pos, btree_level, page_type = struct.unpack("< H H B B", header)
            if page_type != 5 or btree_level != 1:
                continue  # skip non-btree and non-leaf pages

            pos = _align_32bits(page_base + first_item_pos)
            for i in range(item_count):
                wallet_file.seek(pos)
                item_header = wallet_file.read(3)
                if len(item_header) < 3:
                    break
                item_len, item_type = struct.unpack("< H B", item_header)

                if item_type & ~0x80 == 1:
                    # Variable-length key/value item.
                    is_key = (i % 2 == 1)
                    if item_type == 1 and is_key:  # not deleted, and it's a key
                        key_items.append(wallet_file.read(item_len))
                    # value items and deleted items: never read, only
                    # position arithmetic advances past them.
                    pos = _align_32bits(pos + 3 + item_len)
                else:
                    # Fixed-length item type: the 2-byte field read as
                    # item_len above is NOT a length for these -- advance by
                    # the fixed 12-byte item size instead.
                    pos += 12

    return key_items


def load_service_for_coin(coin_name):
    """Instantiate the balance-check service for coin_name, returning None
    (rather than raising) when unavailable."""
    service_class = SERVICES_BY_COIN.get(coin_name)
    if service_class is None:
        return None
    try:
        return service_class()
    except Exception as e:
        print(f"Service unavailable for {coin_name}: {e}")
        return None


def scan_wallet_for_addresses(wallet_path):
    """
    Enumerate every address findable in wallet_path's "key" and "name"
    records, deduplicated. Reports how many records were encrypted (ckey)
    and any record types not deep-parsed in v1.

    :return: {"addresses": [{"address", "source"}, ...],
              "encrypted_key_count": int,
              "unparsed_record_types": {tag: count}}
    """
    addresses = {}
    encrypted_key_count = 0
    unparsed_record_types = {}

    for key_bytes in read_btree_key_items(wallet_path):
        try:
            decoded = decode_bdb_key_record(key_bytes)
        except (IndexError, struct.error):
            continue

        if decoded["type"] == "key":
            address = pubkey_to_address(decoded["pubkey"])
            addresses.setdefault(address, "key")
        elif decoded["type"] == "ckey":
            encrypted_key_count += 1
            address = pubkey_to_address(decoded["pubkey"])
            addresses.setdefault(address, "key")
        elif decoded["type"] == "name":
            addresses.setdefault(decoded["address"], "name")
        else:
            unparsed_record_types[decoded["type"]] = unparsed_record_types.get(decoded["type"], 0) + 1

    return {
        "addresses": [{"address": addr, "source": src} for addr, src in addresses.items()],
        "encrypted_key_count": encrypted_key_count,
        "unparsed_record_types": unparsed_record_types,
    }


def check_addresses_balances(addresses, limit=None):
    """
    Check balance for addresses (list of {"address", "source"} dicts),
    reusing the existing retry helper. Never truncates silently -- reports
    whether a limit was applied.

    :return: {"results": [addr dicts + "balance"], "limited": bool,
              "total_available": int}
    """
    total_available = len(addresses)
    to_check = addresses[:limit] if limit else addresses
    service = load_service_for_coin("Bitcoin")

    results = []
    for entry in to_check:
        balance = _check_balance_with_retries(service, entry["address"]) if service else None
        results.append({**entry, "balance": balance})

    return {
        "results": results,
        "limited": limit is not None and limit < total_available,
        "total_available": total_available,
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Enumerate every address in a Bitcoin Core wallet.dat (not just text-matchable ones) and check balances."
    )
    parser.add_argument("wallet_path", help="Path to the wallet.dat file.")
    parser.add_argument("output_file", help="Output JSON file for results.")
    parser.add_argument("--limit", type=int, default=None, help="Only check the first N addresses (a full scan can be slow/rate-limited).")
    args = parser.parse_args()

    scan = scan_wallet_for_addresses(args.wallet_path)
    checked = check_addresses_balances(scan["addresses"], limit=args.limit)

    output = {
        "encrypted_key_count": scan["encrypted_key_count"],
        "unparsed_record_types": scan["unparsed_record_types"],
        "limited": checked["limited"],
        "total_available": checked["total_available"],
        "results": checked["results"],
    }

    with open(args.output_file, "w") as f:
        json.dump(output, f, indent=4)

    significant = [r for r in checked["results"] if r.get("balance")]
    print(f"Found {scan['encrypted_key_count'] and scan['encrypted_key_count'] or 0} encrypted key record(s) (need a password via unlock_wallet.py to spend).")
    if checked["limited"]:
        print(f"Checked {len(checked['results'])} of {checked['total_available']} addresses (--limit applied).")
    else:
        print(f"Checked all {checked['total_available']} addresses.")
    print(f"{len(significant)} address(es) with a non-zero balance. See {args.output_file}.")
