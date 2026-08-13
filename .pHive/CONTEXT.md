# Project CONTEXT

coin-finder is a Python CLI pipeline that discovers cryptocurrency wallet files on disk, extracts candidate wallet addresses from them, checks those addresses' balances against per-coin blockchain APIs, and filters the results down to wallets worth recovering.

## Terminology

- **Pipeline stage** — one of the four steps `run_pipeline.py` runs in order: search → analyze → check balances → filter. Each stage reads the previous stage's output file and writes its own.
- **Wallet service** — a per-cryptocurrency class in `services/` implementing `WalletService.check_balance(address)`. Adding a coin means adding a service, not modifying pipeline logic.
- **Coin registration** — the three-step process to add a new supported coin: (1) map it in `config/wallet.py`'s `WALLET_SERVICES`, (2) implement `services/<coin>.py`, (3) add a regex in `config/analysis.py`'s `CRYPTO_PATTERNS`.
- **Filtered wallets** — the pipeline's final output (`filtered_wallets.json`): wallet files/addresses that were confirmed to hold a balance, i.e. the ones actually worth recovering.

## Key paths

- `run_pipeline.py` — CLI entry point; orchestrates the four pipeline stages given `<input_dir> <output_dir>`.
- `tools/` — one script per pipeline stage (`search_wallets.py`, `analyze_wallets.py`, `check_wallet_balances.py`, `filter_wallets.py`), each independently runnable.
- `services/` — one `WalletService` subclass per supported coin; `services/__init__.py` defines the base class and loads `.env` via `python-dotenv`.
- `config/search.py` — file extensions/keywords used to find candidate wallet files.
- `config/analysis.py` — regex patterns (`CRYPTO_PATTERNS`) used to extract addresses from candidate files.
- `config/wallet.py` — maps coin names to their `services/` module (`WALLET_SERVICES`).
- `.env.sample` — template for API keys (e.g. `ETHERSCAN_API_KEY`, `BLOCKFROST_API_KEY`) consumed by services that need authenticated APIs.

## Conventions

- snake_case for files/functions; PascalCase for service classes (e.g. `BitcoinService(WalletService)`).
- Pipeline stages fail soft: unreadable files, API errors, and unsupported coins are logged and skipped rather than crashing the run; empty results still produce an (empty) output file.
- No test suite exists yet — see `[[feedback_no_tests]]` if/when that memory is written.
- Security-sensitive: this codebase touches real private keys and wallet secrets. Never log, commit, or transmit key material.

## Canonical references

- `README.md` — usage examples, full supported-coin table (address regex + API provider per coin), and the step-by-step guide for adding a new coin.
- `.pHive/project-profile.yaml` — full discovered tech stack, architecture, and north-star (goals, audience, pain points).
