# Design Discussion: Full wallet.dat Key Enumeration + Balance Scan

**Process note:** same no-live-teammates adaptation as prior epics. This one
started from a live diagnostic finding, not a pre-written plan.

## 1. What Are We Doing?

Diagnostic run against the real `backup-wallet-1/wallet.dat` (using
BTCRecover's own wallet-loading code as a read-only format probe) found **no
`mkey` record** -- this wallet is not encrypted at all. A follow-up raw
Berkeley DB btree walk found **2938 records**: 1009 `key` (raw, unencrypted
private-key records), 900 `keymeta`, 7 `name` (labeled addresses -- exactly
the 7 our regex-based `analyze_wallets.py` found earlier, since these happen
to be stored as base58 text), and many `pool` (keypool) entries. This is not
a password problem for this wallet; it's an under-coverage problem -- 7 of
1009+ possible addresses have ever been checked.

## 2. Approach

1. **Reuse the validated btree page-walk** from live diagnostics run during
   this epic's research (100 leaf pages, 2938 items, zero parse errors against
   the real 917KB wallet file) -- confirmed working before writing any
   production code.
2. **Structural safety property, not just discipline**: Bitcoin Core stores
   `key` records as `BDB-key = (tag "key", pubkey)`, `BDB-value = privkey`,
   and `name` records as `BDB-key = (tag "name", address-string)`,
   `BDB-value = label`. **Every address this tool needs (from both record
   types) lives in the BDB *key* half, never the value half.** The scanner is
   therefore structured to never call `.read()` on a value's file position at
   all -- position arithmetic advances past values using only their length
   header, so private-key bytes are never loaded into memory during this scan,
   not merely ignored after being read.
3. **`tools/scan_wallet_dat.py`**:
   - `read_btree_key_items(wallet_path) -> list[bytes]` -- the safety-critical
     function above.
   - `decode_bdb_key_record(key_bytes) -> dict` -- parses the CDataStream tag
     + payload (compact-size length prefix, per Bitcoin Core's serialization).
     For `tag in ("key", "ckey")`: `{"type": tag, "pubkey": bytes}`. For
     `tag == "name"`: `{"type": "name", "address": str}`. Otherwise:
     `{"type": tag}` (counted, not deep-parsed -- `pool`/`keymeta` are out of
     scope for v1; noted as a follow-up, not silently dropped).
   - `pubkey_to_address(pubkey_bytes)` -- `bip_utils.P2PKHAddrEncoder.EncodeKey`
     (audited library, already used in `match_seed_phrases.py`; verified live
     against the standard BIP44 test vector before use).
   - `scan_wallet_for_addresses(wallet_path) -> list[dict]` -- orchestrates the
     above; returns `[{"address": str, "source": "key"|"name"}, ...]`,
     deduplicated.
   - `check_addresses_balances(addresses, limit=None)` -- reuses
     `_check_balance_with_retries` + `BitcoinService` (no duplicated retry
     logic). `limit` bounds a first pass over potentially 1000+ addresses
     (each balance check is a real network call); when applied, the report
     states the limit explicitly -- never silent truncation.
   - CLI: `python tools/scan_wallet_dat.py <wallet_path> <output_file>
     [--limit N]`.
4. **Encrypted wallets**: if a scan encounters `ckey` records instead of
   `key`, that means the wallet *is* encrypted -- this tool still enumerates
   pubkeys (safe, public data) but cannot check balances meaningfully without
   the decrypted private keys; it reports the encrypted-key count and points
   at `unlock_wallet.py` for password recovery instead of attempting anything
   here.

## 3. What Could Go Wrong

- **critical** (handling) -- Any code path that accidentally reads a value
  position for a `key`/`ckey` record would load a raw private key into memory.
  Mitigated structurally (see Section 2, point 2) rather than by convention
  alone; the review step specifically checks this.
- **medium** -- Checking 1000+ addresses against a live API, each with up to
  3 retries, could take a long time and press against rate limits.
  `--limit` lets the user run a bounded first pass; full sweeps are the
  user's call, not something this epic runs to completion against the real
  file automatically.
- **low** -- `pool`/`keymeta` records aren't deep-parsed in v1. Stated as a
  known gap in the report, not silently absent -- keypool pubkeys are
  genuinely address-bearing and could be a worthwhile follow-up if the `key`/
  `name` sweep doesn't find the "5 coins" wallet.

## 4. Verification Strategy

```
VERIFICATION PLAN:
  Tools: pytest
  Automated: decode_bdb_key_record() against hand-constructed byte sequences
    matching the exact format observed live (key/name/unknown tags);
    pubkey_to_address() against the standard BIP44 test vector (verified
    live); check_addresses_balances() with a mocked BitcoinService (no real
    network calls in the test suite); read_btree_key_items() against a
    small synthetic single-page BDB-shaped fixture built in the test file
  Manual: a BOUNDED (--limit) real run against the actual
    backup-wallet-1/wallet.dat to sanity-check real output -- not a full
    1000+-address sweep during this session (that belongs to the user,
    given the time/rate-limit cost); confirmed the parser handles the real
    file's full page/item structure without errors during research
  Not verifying: pool/keymeta record parsing (explicitly deferred)
```

## 5. Scale Assessment

```
SCALE ASSESSMENT:
  Files affected: ~3 (new tools/scan_wallet_dat.py, new
    tests/test_scan_wallet_dat.py, README.md edit)
  RECOMMENDATION: Proceed to a single story
```
