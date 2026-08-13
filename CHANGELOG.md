# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

## [0.9.0] - 2026-08-13

### Added

- **Full wallet.dat key enumeration + balance scan.** New standalone tool
  (`tools/scan_wallet_dat.py`) parses a Bitcoin Core `wallet.dat`'s actual
  Berkeley DB structure to enumerate every address it contains, not just the
  ones a text regex happens to match. Real-world validation against a real
  wallet found 1016 unique addresses versus the 7 previously ever checked
  (0.7% prior coverage). If the wallet has encrypted (`ckey`) records, this
  tool still finds those addresses safely and reports that a password is
  needed to spend from them (see `unlock_wallet.py`).
  **Safety property enforced structurally, not just by convention:** every
  address needed lives in the database *key* half of each record; the
  *value* half, where private keys are stored, is skipped via position
  arithmetic and is never read from disk during a scan -- private key bytes
  never enter memory in the first place, this isn't a "don't print it" rule.
  `--limit` bounds a first pass since checking hundreds of addresses live can
  take a while.

## [0.8.0] - 2026-08-13

### Added

- **BTCRecover wallet-unlock integration.** New `scripts/install_btcrecover.sh`
  installs [BTCRecover](https://github.com/3rdIteration/btcrecover) (the
  actively maintained Python 3 fork -- the original `gurnec/btcrecover` is
  Python 2-only and no longer runs) into `vendor/btcrecover/`. New standalone
  tool `tools/unlock_wallet.py` wraps it to test candidate passwords against
  a real wallet file (Bitcoin Core, Armory, Electrum, and more).
  **Critical safety property:** the tool enforces BTCRecover's own documented
  "separation principle" (from its bundled `SKILL.md`, written for AI
  agents) with a hard gate -- it refuses to run unless the machine is
  verified offline, since a real recovery run must never happen on a
  network-connected session. Candidates are read from a file only, never a
  command-line argument. Tested only against BTCRecover's own public test
  fixture, not any real wallet.
- First Mermaid pipeline diagram in the README, showing how all nine tools
  relate.

## [0.7.0] - 2026-08-13

### Added

- **Seed-phrase HD derivation + balance matcher.** New standalone tool
  (`tools/match_seed_phrases.py`) turns a candidate seed phrase into an
  answer: derives addresses across a bounded set of known schemes
  (BIP44/BIP49/BIP84 for Bitcoin, BIP44 for Ethereum/Litecoin) via `bip_utils`
  (audited BIP32/39/44/49/84 library), and checks each against real balances
  using the project's existing balance-check services. Never computes or
  exposes a private key -- addresses only. Same secret-handling discipline as
  the seed-phrase finder: phrases are read from a file only (never a CLI
  argument), never printed to the console, and the report only repeats
  phrase text for phrases that actually produced a balance. v1's scheme
  coverage is intentionally bounded; a more exhaustive "deep dive" mode for
  exotic old-wallet schemes is planned as a future tool. (`seed-derivation-balance-check` epic)

## [0.6.0] - 2026-08-13

### Added

- **Seed-phrase finder.** New standalone tool (`tools/find_seed_phrases.py`)
  scans text files for candidate BIP39 backup seed phrases, using real
  checksum validation (`mnemonic` library, first production dependency added
  since kickoff) rather than just wordlist membership -- much fewer false
  positives than naive word-matching. Security-critical: found phrase text is
  never printed to the console, only written to the local output file, since a
  valid seed phrase is real private-key material. v1 is text-files only;
  OCR for image-embedded phrases is a known, explicitly deferred gap.
  (`seed-phrase-finder` epic)

## [0.5.0] - 2026-08-13

### Added

- **Dormancy/last-activity reporting.** `crawl_transaction_graph.py` now shows
  years-since-last-activity for every discovered address, with an explicit
  call-out on anything dormant 5+ years -- lets you verify your own
  assumptions about a wallet's history against the real blockchain record.

### Fixed

- **Standalone tool invocation.** Every `tools/*.py` that imports
  `config`/`services` (`search_wallets.py`, `analyze_wallets.py`,
  `check_wallet_balances.py`, `build_wallet_graph.py`,
  `crawl_transaction_graph.py`) now works when run directly as
  `python tools/foo.py ...`, per the README's documented usage. This was
  broken pre-existing (Python only puts the script's own directory on the
  import path, not the repo root) -- confirmed identically broken on
  `search_wallets.py`, so not introduced by recent epics.

## [0.4.0] - 2026-08-13

### Added

- **Blockchain transaction-graph crawler.** New standalone tool
  (`tools/crawl_transaction_graph.py`) that discovers other Bitcoin addresses
  likely owned by the same person, starting from one known address -- using
  only public blockchain data (no private keys). Uses common-input-ownership
  (co-spend) clustering as the primary, high-confidence signal, plus bounded
  output-following for lower-confidence "where did it go" discovery, guarded
  against mining-pool/exchange-style high-fanout transactions. Validated
  against a real found address -- discovered a second real address holding a
  non-zero balance. (`transaction-graph-crawler` epic)

### Fixed

- Confirmed (not yet fixed) a pre-existing bug: standalone tool invocation per
  the README (`python tools/foo.py ...`) fails for any tool importing
  `config`/`services` unless `PYTHONPATH=.` is set, because Python only puts
  the script's own directory on the import path. Reproduced on
  `search_wallets.py` too -- not introduced by recent epics. Tracked as a
  follow-up.

## [0.3.0] - 2026-08-13

### Added

- **Hidden/encrypted volume detection.** New standalone tool
  (`tools/detect_hidden_volumes.py`) flags files that look like VeraCrypt/
  TrueCrypt-style encrypted containers, using an entropy + magic-byte heuristic
  with no upper file-size bound -- built for scanning old hard drives and
  backups, not just small wallet files. Detect-and-flag only: prints manual-mount
  guidance and never attempts to guess, brute-force, or crack a password. Not
  wired into the default `run_pipeline.py` run -- invoked deliberately against a
  drive you suspect has a hidden container. (`deep-crawl-hidden-volumes` epic)

## [0.2.0] - 2026-08-13

### Added

- **Conservative balance-check retries.** Balance checks now retry up to 3 times
  (2s backoff) before giving up on an address, instead of settling on "no balance"
  after a single flaky API call. Addresses still inconclusive after retries are
  written to `inconclusive_balances.json` alongside `wallet_balances.json`, so
  they stay visible as "needs a recheck" rather than silently disappearing.
  (`conservative-balance-retries` epic)

## [0.1.0] - 2026-08-13

### Added

- **Wallet & coin relationship graph.** New pipeline stage
  (`tools/build_wallet_graph.py`) correlating discovered wallets/coins across
  every scanned file: duplicate-address confirmations, multi-coin file
  detection, and coverage-gap nudges. Runs automatically as pipeline stage 5,
  writing `wallet_relationships.json` and `wallet_relationships.md`.
  (`wallet-relationship-graph` epic)
- First test suite in the repo (`pytest`, dev-only dependency).
