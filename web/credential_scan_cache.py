import struct
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.scan_wallet_dat import decode_bdb_key_record, pubkey_to_address, read_btree_key_items
from web.paths import app_data_dir

DEFAULT_DB_PATH = app_data_dir() / "credential_scan_cache.db"

# ccu-03: the heavier half of the credential-completeness signal --
# whether a private key is structurally EXTRACTABLE (unencrypted "key"
# record -- no password needed at all) or genuinely ENCRYPTED ("ckey"
# record -- a real dead end without a password), per address, for
# Bitcoin Core wallet.dat findings only. Two tables, both keyed by
# wallet_path (not per-address alone -- a row in credential_scan_wallets
# always exists once a wallet has been scanned at all, distinguishing
# "never scanned" (no row) from "scanned, not a wallet.dat" (row with
# is_wallet_dat=0) from "scanned, IS a wallet.dat" (is_wallet_dat=1, zero
# or more rows in credential_scan_addresses).
#
# Deliberately NO column anywhere for actual key material (WIF/DER
# bytes) -- this cache only ever stores addresses (already public) and a
# key_type label ("key"/"ckey"), the same "metadata only" discipline
# auto_unlock_history.py documents for its own schema.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS credential_scan_wallets (
    wallet_path TEXT PRIMARY KEY,
    is_wallet_dat INTEGER NOT NULL,
    scanned_at REAL NOT NULL,
    error TEXT
);
CREATE TABLE IF NOT EXISTS credential_scan_addresses (
    wallet_path TEXT NOT NULL,
    address TEXT NOT NULL,
    key_type TEXT NOT NULL,
    PRIMARY KEY (wallet_path, address)
);
"""

# Columns added after credential_scan_addresses' original release --
# `CREATE TABLE IF NOT EXISTS` above only applies to a brand new db file;
# an existing credential_scan_cache.db on disk from before a column
# existed needs it added explicitly. Each entry is a full `ALTER TABLE`
# statement, run on every connect; `ADD COLUMN` on a column that already
# exists raises OperationalError, treated below as "already migrated".
# Same precedent as findings.py's own _MIGRATIONS list.
#
# bpk-01: extracted_at REAL, nullable -- a timestamp marking that a
# structurally-extractable ("key") address's private key has actually
# been extracted and copied out at least once, distinct from merely
# "extractable." Deliberately never the WIF itself -- see this module's
# top-of-file "metadata only" discipline; extracted_at is a "this already
# happened" marker, not a retrieval mechanism.
_MIGRATIONS = [
    "ALTER TABLE credential_scan_addresses ADD COLUMN extracted_at REAL",
]


def _connect(db_path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    for statement in _MIGRATIONS:
        try:
            conn.execute(statement)
        except sqlite3.OperationalError:
            pass  # already migrated
    return conn


def scan_wallet_key_types(wallet_path):
    """
    Full-file classification of every key/ckey record in wallet_path,
    keyed by derived address -- "key" (unencrypted, structurally
    extractable, no password needed at all) or "ckey" (encrypted,
    genuinely locked without a password).

    Built entirely on scan_wallet_dat.py's own read_btree_key_items,
    reused read-only and unmodified -- that function already walks every
    BDB leaf page and returns only the KEY-half bytes of every
    non-deleted item (its own docstring: "SAFETY-CRITICAL: value-half
    file positions are skipped via their length header alone -- never
    .read()"). This function derives an address from each key/ckey
    item's pubkey and records its type; it never touches a single
    value-half byte, so unlike extract_private_key.py's
    find_key_value_pair_for_address (which does read one record's value
    bytes once its target address matches), this scan never comes near
    actual private key material at all -- it only ever produces public
    addresses plus a type label.

    This is the same full linear pass over the wallet.dat file (real,
    non-trivial I/O scaling with the file's page count) that this
    story's cache exists to avoid re-running on every Findings page
    load -- one pass records every address's key-type at once, which is
    why the cache is keyed by wallet_path rather than by
    (wallet_path, address).

    :return: {address: "key"|"ckey"}
    :raises AssertionError: not a recognized Bitcoin Core wallet.dat
        (Btree v9) -- read_btree_key_items' own magic check, propagated
        unchanged.
    """
    key_types = {}
    for key_bytes in read_btree_key_items(wallet_path):
        try:
            decoded = decode_bdb_key_record(key_bytes)
        except (IndexError, struct.error):
            continue
        if decoded["type"] in ("key", "ckey"):
            address = pubkey_to_address(decoded["pubkey"])
            # A real wallet should never have the same address as both an
            # unencrypted key and an encrypted ckey record; if a
            # corrupted/resumed file somehow does, keep whichever was
            # seen first rather than silently overwriting -- same
            # setdefault discipline scan_wallet_dat.py's own
            # scan_wallet_for_addresses() uses for its address dict.
            key_types.setdefault(address, decoded["type"])
    return key_types


def record_credential_scan(wallet_path, is_wallet_dat, key_types=None, error=None, db_path=DEFAULT_DB_PATH):
    """
    Upserts one wallet's scan outcome. Address rows for this wallet_path
    are replaced wholesale (delete-then-insert) rather than merged, so a
    re-scan reflects exactly what the file contains now -- wallet files
    don't change once discovered (this project's own working assumption
    for this cache), so in practice this only ever runs once per wallet,
    but an explicit re-scan must never leave stale rows behind.

    :param is_wallet_dat: False for a file that isn't a recognized
        Bitcoin Core wallet.dat (or couldn't be read at all) -- key_types
        is ignored in that case.
    :param key_types: {address: "key"|"ckey"} -- the exact shape
        scan_wallet_key_types() returns.
    :param error: the scan failure's message, for a non-wallet_dat
        result; None for a clean scan (even one that found zero
        key/ckey records, e.g. a watch-only wallet).
    """
    key_types = key_types or {}
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO credential_scan_wallets (wallet_path, is_wallet_dat, scanned_at, error)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(wallet_path) DO UPDATE SET
                is_wallet_dat = excluded.is_wallet_dat,
                scanned_at = excluded.scanned_at,
                error = excluded.error
            """,
            (wallet_path, 1 if is_wallet_dat else 0, time.time(), error),
        )
        conn.execute("DELETE FROM credential_scan_addresses WHERE wallet_path = ?", (wallet_path,))
        if is_wallet_dat and key_types:
            conn.executemany(
                "INSERT INTO credential_scan_addresses (wallet_path, address, key_type) VALUES (?, ?, ?)",
                [(wallet_path, address, key_type) for address, key_type in key_types.items()],
            )
        conn.commit()
    finally:
        conn.close()


def scan_and_record_wallet(wallet_path, db_path=DEFAULT_DB_PATH):
    """
    Runs scan_wallet_key_types() against one wallet_path and records the
    outcome, catching any scan failure (bad magic, truncated/unreadable
    file, ...) rather than letting one bad file abort a batch job -- a
    failure is itself a meaningful, cacheable result (is_wallet_dat=False
    with the error message), not something to retry live on the next
    page load.

    :return: {"wallet_path", "is_wallet_dat", "key_count", "ckey_count", "error"}
    """
    try:
        key_types = scan_wallet_key_types(wallet_path)
    except Exception as e:
        record_credential_scan(wallet_path, is_wallet_dat=False, key_types=None, error=str(e), db_path=db_path)
        return {"wallet_path": wallet_path, "is_wallet_dat": False, "key_count": 0, "ckey_count": 0, "error": str(e)}

    record_credential_scan(wallet_path, is_wallet_dat=True, key_types=key_types, error=None, db_path=db_path)
    key_count = sum(1 for t in key_types.values() if t == "key")
    ckey_count = sum(1 for t in key_types.values() if t == "ckey")
    return {"wallet_path": wallet_path, "is_wallet_dat": True, "key_count": key_count, "ckey_count": ckey_count, "error": None}


def run_credential_scan(wallet_paths, db_path=DEFAULT_DB_PATH):
    """
    Background-job entry point for the Findings "Check credential status"
    action (web/app.py, via run_job()) -- scans every given wallet_path
    once and records each into the cache.

    Deliberately NOT a secret=True job (unlike extract-key/auto-unlock):
    no private key material is ever read here (see scan_wallet_key_types'
    own docstring) -- only addresses (already public) and a key_type
    label are produced, so this job's result is safe to leave visible via
    the normal get_job()/list_jobs()/item_result.html path like any other
    non-sensitive job (crawl, fork-coins, ...).

    :return: {"report": str, "results": [scan_and_record_wallet's return
        dict, ...]}
    """
    results = [scan_and_record_wallet(wallet_path, db_path=db_path) for wallet_path in wallet_paths]

    extractable_total = sum(r["key_count"] for r in results)
    encrypted_total = sum(r["ckey_count"] for r in results)
    not_wallet_dat = [r for r in results if not r["is_wallet_dat"]]

    lines = [
        f"Checked {len(results)} wallet file(s):",
        f"  {extractable_total} unencrypted (extractable) key record(s) found",
        f"  {encrypted_total} encrypted (ckey) key record(s) found",
        f"  {len(not_wallet_dat)} file(s) were not a recognized Bitcoin Core wallet.dat",
    ]
    for r in not_wallet_dat:
        lines.append(f"    {r['wallet_path']}: {r['error']}")

    return {"report": "\n".join(lines), "results": results}


def mark_address_extracted(wallet_path, address, db_path=DEFAULT_DB_PATH):
    """
    bpk-01: records that a (wallet_path, address) pair's private key has
    already been extracted, by stamping extracted_at to now. This story
    only builds this marking function and the schema/badge/checkbox that
    read it -- bpk-02 is what actually calls this after a real extraction
    succeeds; no extraction logic runs here.

    Only ever writes a timestamp -- never accepts or stores the actual
    private key value, keeping this cache's "metadata only" discipline
    intact. A no-op (zero rows affected) if the pair has no existing row
    (e.g. address vanished from a later re-scan) -- there is nothing to
    mark and this must not fabricate a row.

    Re-marking is safe and idempotent: calling this again just moves
    extracted_at forward, consistent with re-extraction being a safe,
    read-only, self-verifying operation (per tools/extract_private_key.py's
    own extraction function's docstring) rather than a one-shot lock.
    """
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE credential_scan_addresses SET extracted_at = ? WHERE wallet_path = ? AND address = ?",
            (time.time(), wallet_path, address),
        )
        conn.commit()
    finally:
        conn.close()


def credential_status_index(db_path=DEFAULT_DB_PATH):
    """
    Cheap, always-live read of the whole cache -- the join Findings uses
    on every page render (same "small personal-scale table, safe to read
    in full every time" assumption auto_unlock_history.py's own
    latest_status_by_wallet_path() already makes). Never runs the BDB
    scan itself -- only reads what a past "Check credential status" job
    already recorded.

    :return: {wallet_path: {"is_wallet_dat": bool, "scanned_at": float,
        "error": str|None, "addresses": {address: "key"|"ckey"},
        "extracted_at": {address: float|None}}}. "addresses" keeps its
        pre-bpk-01 shape unchanged (a plain key_type string per address)
        -- extracted_at is a sibling dict, same address keys, so existing
        callers reading "addresses" are unaffected. A wallet_path never
        scanned is simply absent -- callers treat that as "not checked
        yet" (folded into the same "not checked / not applicable" badge
        state as a genuinely non-wallet.dat finding, per this story's
        4-state design).
    """
    conn = _connect(db_path)
    try:
        wallet_rows = conn.execute("SELECT * FROM credential_scan_wallets").fetchall()
        address_rows = conn.execute("SELECT * FROM credential_scan_addresses").fetchall()
    finally:
        conn.close()

    index = {
        row["wallet_path"]: {
            "is_wallet_dat": bool(row["is_wallet_dat"]),
            "scanned_at": row["scanned_at"],
            "error": row["error"],
            "addresses": {},
            "extracted_at": {},
        }
        for row in wallet_rows
    }
    for row in address_rows:
        wallet = index.setdefault(
            row["wallet_path"],
            {"is_wallet_dat": True, "scanned_at": None, "error": None, "addresses": {}, "extracted_at": {}},
        )
        wallet["addresses"][row["address"]] = row["key_type"]
        wallet["extracted_at"][row["address"]] = row["extracted_at"]
    return index
