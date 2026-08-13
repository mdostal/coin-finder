import struct
import sys
from pathlib import Path

from bip_utils import Secp256k1PrivateKey, WifDecoder, WifEncoder, WifPubKeyModes

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.scan_wallet_dat import EXPECTED_MAGIC, _align_32bits, _read_compact_size, decode_bdb_key_record, pubkey_to_address
from tools.unlock_wallet import check_network_status


def find_key_value_pair_for_address(wallet_path, target_address):
    """
    Walks the same BDB leaf-page structure as scan_wallet_dat.py's
    read_btree_key_items, but this time also captures the paired VALUE-half
    bytes for the one "key"/"ckey" item whose derived address matches
    target_address -- every other value-half in the file stays unread,
    exactly like the read-only scan; only the one address explicitly asked
    for here ever has its value bytes touched.

    In a BDB leaf page, each key item is immediately preceded by its paired
    value item (this pairing was already established and validated in
    scan_wallet_dat.py's read_btree_key_items -- reused here, not
    re-derived).

    :return: {"key_type": "key"|"ckey", "value_bytes": bytes, "pubkey_len": int}
        or None if target_address isn't found among this wallet's key/ckey records.
    """
    with open(wallet_path, "rb") as wallet_file:
        wallet_file.seek(12)
        assert wallet_file.read(8) == EXPECTED_MAGIC, "not a recognized Bitcoin Core wallet.dat (Btree v9)"

        wallet_file.seek(20)
        page_size = struct.unpack("<I", wallet_file.read(4))[0]
        import os

        wallet_file_size = os.path.getsize(wallet_path)

        for page_base in range(page_size, wallet_file_size, page_size):
            wallet_file.seek(page_base + 20)
            header = wallet_file.read(6)
            if len(header) < 6:
                continue
            item_count, first_item_pos, btree_level, page_type = struct.unpack("< H H B B", header)
            if page_type != 5 or btree_level != 1:
                continue

            pos = _align_32bits(page_base + first_item_pos)
            pending_value = None  # (pos, item_len) of the immediately preceding value item

            for i in range(item_count):
                wallet_file.seek(pos)
                item_header = wallet_file.read(3)
                if len(item_header) < 3:
                    break
                item_len, item_type = struct.unpack("< H B", item_header)

                if item_type & ~0x80 == 1:
                    is_key = (i % 2 == 1)
                    if item_type == 1 and is_key:
                        key_bytes = wallet_file.read(item_len)
                        try:
                            decoded = decode_bdb_key_record(key_bytes)
                        except (IndexError, struct.error):
                            decoded = None

                        if decoded and decoded["type"] in ("key", "ckey") and pending_value is not None:
                            address = pubkey_to_address(decoded["pubkey"])
                            if address == target_address:
                                value_pos, value_len = pending_value
                                wallet_file.seek(value_pos)
                                value_bytes = wallet_file.read(value_len)
                                return {
                                    "key_type": decoded["type"],
                                    "value_bytes": value_bytes,
                                    "pubkey_len": len(decoded["pubkey"]),
                                }
                        pending_value = None
                    elif item_type == 1 and not is_key:
                        pending_value = (pos + 3, item_len)
                    else:
                        pending_value = None
                    pos = _align_32bits(pos + 3 + item_len)
                else:
                    pending_value = None
                    pos += 12

    return None


def _der_element_length(data):
    """
    Total byte length (tag + length-prefix + content) of the DER element
    starting at data[0] -- standard DER length-prefix parsing (a fixed,
    well-defined encoding rule, not a cryptographic operation) so the
    trailing creation-timestamp bytes Bitcoin Core appends after the DER
    blob can be sliced off before handing the blob to a strict DER parser.
    """
    if data[0] != 0x30:
        raise ValueError("expected a DER SEQUENCE (0x30) at the start of this value")

    first_length_byte = data[1]
    if first_length_byte & 0x80 == 0:
        return 2 + first_length_byte

    num_length_bytes = first_length_byte & 0x7F
    content_length = int.from_bytes(data[2 : 2 + num_length_bytes], "big")
    return 2 + num_length_bytes + content_length


def _extract_raw_private_key_from_der(der_bytes):
    """
    Extracts the raw 32-byte secp256k1 private key scalar directly from a
    CPrivKey DER blob's fixed SEC1 structure:
    SEQUENCE { INTEGER version(=1), OCTET STRING privateKey[32], ...optional
    fields we don't need... }.

    Does NOT use a general-purpose DER/EC-key loader: `cryptography`'s own
    `load_der_private_key` refuses this exact key material, because Bitcoin
    Core's OpenSSL-produced DER blobs encode secp256k1's curve parameters
    *explicitly* rather than by named-curve OID, and `cryptography`
    deliberately restricts explicit-parameter EC keys to a NIST-curve
    allowlist -- a sound anti-footgun policy for a general-purpose library,
    but incompatible with this well-known, decade-old Bitcoin Core quirk.

    Every field read here is a fixed tag/length this format always uses
    (version is always INTEGER value 1; the private key is always a 32-byte
    OCTET STRING for secp256k1) and is asserted against its expected value
    before use -- any mismatch raises rather than silently extracting the
    wrong bytes. extract_wif_for_address() additionally re-derives the
    address from the result and refuses to return anything that doesn't
    match, as an independent, second correctness check on top of this one.
    """
    if der_bytes[0] != 0x30:
        raise ValueError(f"expected a DER SEQUENCE (0x30), got {der_bytes[0]:#x}")
    first_length_byte = der_bytes[1]
    pos = 2 + (first_length_byte & 0x7F) if first_length_byte & 0x80 else 2

    if der_bytes[pos] != 0x02:
        raise ValueError(f"expected an INTEGER (0x02) for the CPrivKey version field, got {der_bytes[pos]:#x}")
    version_len = der_bytes[pos + 1]
    version_value = int.from_bytes(der_bytes[pos + 2 : pos + 2 + version_len], "big")
    if version_value != 1:
        raise ValueError(f"expected CPrivKey version 1, got {version_value}")
    pos += 2 + version_len

    if der_bytes[pos] != 0x04:
        raise ValueError(f"expected an OCTET STRING (0x04) for the private key field, got {der_bytes[pos]:#x}")
    key_len = der_bytes[pos + 1]
    pos += 2
    if key_len != 32:
        raise ValueError(f"expected a 32-byte secp256k1 private key, got {key_len} bytes")

    return bytes(der_bytes[pos : pos + 32])


def decode_cprivkey_to_wif(value_bytes, compressed):
    """
    value_bytes is a Bitcoin Core "key" record's value: a compact-size
    length prefix, followed by that many bytes of DER-encoded EC private
    key (CPrivKey), followed by additional wallet metadata this function
    does not need and never reads.

    Cross-validated before trusting the slice: the compact-size prefix's
    declared length must exactly match the DER SEQUENCE's own
    self-described length (via _der_element_length()'s plain length-prefix
    parsing). If they disagree, this isn't the expected format and this
    function refuses rather than guessing which length is right. WIF
    encoding uses bip_utils' own WifEncoder (already used elsewhere in this
    project) -- an encoding step, not a cryptographic one.
    """
    declared_len, der_offset = _read_compact_size(value_bytes, 0)
    der_bytes = bytes(value_bytes[der_offset : der_offset + declared_len])

    self_described_len = _der_element_length(der_bytes)
    if self_described_len != declared_len:
        raise ValueError(
            f"CPrivKey length mismatch: compact-size prefix declared {declared_len} bytes, but the "
            f"DER SEQUENCE's own length is {self_described_len} bytes -- refusing to guess which is correct."
        )

    raw_key_bytes = _extract_raw_private_key_from_der(der_bytes)
    pub_key_mode = WifPubKeyModes.COMPRESSED if compressed else WifPubKeyModes.UNCOMPRESSED
    return WifEncoder.Encode(raw_key_bytes, pub_key_mode=pub_key_mode)


def extract_wif_for_address(wallet_path, target_address, allow_online=False):
    """
    HARD SAFETY GATE: refuses (no key material ever touched) unless the
    machine is verified offline -- same discipline as unlock_wallet.py,
    applied here because this function's entire job is producing a real,
    spendable secret.

    Only supports unencrypted "key" records. "ckey" (password-encrypted)
    records need the wallet's own password + AES handling -- out of scope
    for this narrowly-focused tool; raises a clear error rather than
    mishandling encrypted bytes as if they were a plain DER key.

    Self-verifies before returning: re-derives the address from the WIF it
    is about to hand back and confirms it matches target_address exactly.
    This function must never hand back a WIF for the wrong key.

    :return: WIF string.
    :raises RuntimeError: offline-gate refusal, address not found, an
        encrypted (ckey) record, or (should never happen) a self-verification mismatch.
    """
    if not allow_online:
        status = check_network_status()
        if status != "OFFLINE":
            raise RuntimeError(
                f"Refusing to extract a private key: network status is {status}, not OFFLINE. "
                "Handling real key material must happen with network disabled -- disconnect and "
                "try again, or pass allow_online=True (--allow-online on the CLI) only for known-safe test data."
            )

    found = find_key_value_pair_for_address(wallet_path, target_address)
    if found is None:
        raise RuntimeError(f"Address not found among this wallet's key/ckey records: {target_address}")

    if found["key_type"] == "ckey":
        raise RuntimeError(
            f"{target_address} is in an ENCRYPTED (ckey) record -- this tool only extracts from "
            "unencrypted wallets. Use unlock_wallet.py (BTCRecover) to recover the password first."
        )

    compressed = found["pubkey_len"] == 33
    wif = decode_cprivkey_to_wif(found["value_bytes"], compressed=compressed)

    key_bytes, _ = WifDecoder.Decode(wif)
    pub_key_mode = WifPubKeyModes.COMPRESSED if compressed else WifPubKeyModes.UNCOMPRESSED
    derived_pubkey_obj = Secp256k1PrivateKey.FromBytes(key_bytes).PublicKey()
    derived_pubkey = (
        derived_pubkey_obj.RawCompressed().ToBytes()
        if pub_key_mode == WifPubKeyModes.COMPRESSED
        else derived_pubkey_obj.RawUncompressed().ToBytes()
    )
    derived_address = pubkey_to_address(derived_pubkey)
    if derived_address != target_address:
        raise RuntimeError(
            "Self-verification failed: the extracted key does not derive back to the requested "
            f"address ({derived_address} != {target_address}). Refusing to return it."
        )

    return wif


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract one address's private key (WIF) from an UNENCRYPTED Bitcoin Core wallet.dat. "
        "Never prints the key -- writes it to a local file only."
    )
    parser.add_argument("wallet_path", help="Path to the wallet.dat file.")
    parser.add_argument("address", help="The address whose private key to extract.")
    parser.add_argument("output_file", help="Local file to write the WIF key to (never printed to the console).")
    parser.add_argument(
        "--allow-online",
        action="store_true",
        help="Override the offline safety gate. Only use this for known-safe test data -- "
        "real key extraction must happen with network disabled.",
    )
    args = parser.parse_args()

    try:
        wif = extract_wif_for_address(args.wallet_path, args.address, allow_online=args.allow_online)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    with open(args.output_file, "w") as f:
        f.write(wif + "\n")

    print(f"WIF private key for {args.address} written to {args.output_file}.")
    print("Do not share this file. Import it into Electrum (Import Bitcoin addresses or private keys), then use")
    print("Electrum's own sweep function to move the full balance to a fresh address you control long-term.")
