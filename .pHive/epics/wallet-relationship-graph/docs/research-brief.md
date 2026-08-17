# Research Brief: Wallet & Coin Relationship Graph

## Requirement

Build a graph view of discovered wallets/coins to surface other wallets that may be
missing — one of the two core `north_star.goal` items captured at kickoff
(`.pHive/project-profile.yaml`), alongside "eventually add a simple UI" (out of scope
for this epic; noted as a later north-star item).

## Codebase findings

### Pipeline data shapes (confirmed by reading `tools/*.py`)

1. `tools/search_wallets.py` → `wallet_search_output.txt`: flat list of candidate file paths (one per line), matched by extension/keyword/coin-name from `config/search.py`.
2. `tools/analyze_wallets.py` → `wallet_analysis.json`: `{file_path: {crypto_name: [address, ...]}}`. Regex patterns come from `config/analysis.py::CRYPTO_PATTERNS` (21 coins).
3. `tools/check_wallet_balances.py` → `wallet_balances.json`: `{file_path: {crypto_name: {address: balance_or_null}}}`. Loads a `WalletService` per coin via `config/wallet.py::WALLET_SERVICES` (dynamic import from `services/`).
4. `tools/filter_wallets.py` → `filtered_wallets.json`: same shape as (3), balances `> 0` only.
5. `run_pipeline.py` threads these four stages together via `<output_dir>/checks/*.json` and a final `filtered_wallets.json`.

No stage currently correlates data **across** files or **across** coins — each file's analysis is independent, and there is no notion of "this address appeared elsewhere" or "this file looks like a multi-coin wallet backup that we've only partially covered."

### Relevant existing patterns to follow

- `services/__init__.py` (`WalletService` base class) — 15 lines, defines the `check_balance(address)` contract every coin service implements. New code should follow the same "small, single-purpose class/function" style.
- `tools/filter_wallets.py` (30 lines) — simplest existing tool; good template for a new stage: read one JSON, transform, write another JSON, thin argparse CLI wrapper.
- `run_pipeline.py` — shows how a new stage would slot into the orchestrator (read prior stage's output path, write to `<output_dir>/checks/`, print a one-line status).

### Gaps / no coverage today

- No test suite exists anywhere in the repo (confirmed at kickoff: `code_quality.test_first_signals.test_absence: true`). This epic's methodology is `tdd` (`hive.config.yaml → execution.default_methodology`), so this is the first code in the repo to land with tests — establishes the pattern for everything after it.
- No graph/relationship data structure exists. This is wholly new capability, not a refactor.
- `requirements.txt` has only `requests` and `python-dotenv` — no graph/viz library. README explicitly distrusts pulling in unvetted third-party libraries ("I'd want to check to see if they were trojans"), so the design should stay stdlib-only unless there's a strong reason not to.

## Context7 / library validation

Not applicable — no new library/SDK is being introduced (stdlib-only `json`, `collections`, `argparse`). No validation escalation needed.

## Cross-cutting concerns loaded

From `.pHive/cross-cutting-concerns.yaml`: only the `documentation` concern is defined (no template matched this Python-CLI project at kickoff). It applies here: README's "Pipeline Overview" section and file-structure tree will need a new stage documented.

## Confidence

High — all findings are grounded in direct reads of the four `tools/*.py` files and `run_pipeline.py`, not inference.
