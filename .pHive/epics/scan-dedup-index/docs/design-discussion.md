# Design Discussion: Persistent Scan Dedup Index

**Process note:** same no-live-teammates adaptation as prior epics this
session. Requested directly ("I could be running file finds... and then
we can then index and find the DUPLICATE wallets on my other things so we
DON'T rehash it... THEN let it run for days figuring out what it needs to").

## 1. What Are We Doing?

Scanning multiple overlapping drives/backups means the same wallet.dat (or
other candidate file) gets found and re-analyzed every time, at a
different path each time (a backup copy, a cloned drive). The expensive
part of `find()` is `analyze_wallets`' per-file regex pass across every
`CRYPTO_PATTERNS` entry -- worth skipping entirely for a file whose exact
content has already been analyzed once, regardless of where it now lives.

## 2. What I Found

- `tools/search_wallets.py`'s `search_for_wallets()` walks a tree and
  filters candidates by extension/keyword/size -- no hashing today.
- `tools/analyze_wallets.py`'s `analyze_wallet_file(file_path)` already
  reads the full file into memory (`f.read()`) to run the regex patterns
  against it -- the exact bytes needed for a content hash are already
  loaded there, no extra I/O required to add hashing at that point.
- No existing persistent, cross-run store in `tools/` -- every existing
  piece of durable state (`findings.db`, `crawl_runs.db`) lives in `web/`
  and resolves its path via `web/paths.py`'s `app_data_dir()`. That module
  has zero Flask dependency (confirmed: `web/__init__.py` is empty,
  `web/paths.py` only imports `sys`/`pathlib`) -- safe for `tools/` to
  import directly without pulling in the Flask app.

## 3. My Proposed Approach

**New `tools/scan_index.py`** (sqlite, `app_data_dir() / "scan_index.db"`,
same `_connect`/`_SCHEMA` pattern as `web/findings.py`):
- `hash_file_bytes(content: bytes) -> str` -- sha256 hexdigest.
- `is_known(file_hash, db_path=...) -> dict | None` -- the previously
  recorded per-file coin->addresses result, or `None`.
- `record_scanned_file(file_hash, file_path, results, db_path=...)`.
- `list_scanned_files(db_path=...)` / `clear_scan_index(db_path=...)` --
  management + the reversible-vs-destructive pattern established by
  `findings.py`/`crawl_runs.py`.

**`tools/analyze_wallets.py`** gains an optional `index_db_path=None`
parameter on `analyze_wallets()`. `None` (default) is a complete no-op --
byte-identical behavior to today, every existing test untouched. When a
path is given: for each candidate file, read it once, hash it, check
`scan_index.is_known()`. A hit reuses the recorded result and skips the
regex pass entirely (the actual savings). A miss runs
`analyze_wallet_file()` as today (a second read inside that call -- a
deliberate, accepted tradeoff: keeps `analyze_wallet_file()` itself
byte-for-byte unchanged, zero regression risk, and the double-read only
happens for genuinely new files, which is the expected common case on a
fresh drive), then records the hash+result for next time.

**`run_pipeline.py`'s `find()`** gains the same passthrough
`index_db_path=None` parameter to `analyze_wallets()`.

**`web/app.py`'s `_run_find_job`** always passes
`tools.scan_index.DEFAULT_DB_PATH` -- dedup is on by default for the app
(the whole point is multi-drive scans over days), with a checkbox on the
scan form ("Skip files identical to ones already scanned before") to turn
it off per-scan if ever wanted.

**Management**: a small card on the scan page (`index.html`) showing how
many files are in the index, with a clear action -- mirrors
`findings_clear_all`/`group_view_clear`'s confirm-guarded pattern exactly.

## 4. Risks

- **Double I/O read for new files.** Accepted tradeoff, see above --
  bounded to wallet-candidate files only (already size-capped by the
  search stage), not the whole drive.
- **Hash collisions.** sha256 -- not a real-world risk at this scale.

## 5. Scale Assessment

**Small.** 4 files touched (1 new: `tools/scan_index.py`; 3 extended:
`analyze_wallets.py`, `run_pipeline.py`, `web/app.py`) plus one template
addition. Same shape as every prior epic this session -- design discussion
is sufficient, proceeding directly to stories.
