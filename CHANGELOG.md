# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

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
