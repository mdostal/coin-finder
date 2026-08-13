# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

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
