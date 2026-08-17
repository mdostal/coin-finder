# Research Brief: local-web-ui

## Requirement

Build a local web UI that ties together every existing coin-finder tool into one
cohesive app -- a Disk-Drill-style experience for wallet recovery. Pick a
drive/directory, scan it, see found wallets/candidates in one place, attempt
unlocks, view balances/relationship graphs, and copy files to a safe staging
area. Runs as a local browser app first (`python app.py`, open
`http://127.0.0.1:5000`); an Electron wrapper is a separate, later effort the
user owns outside this epic.

## Existing surface area (13 tools + 1 pipeline entrypoint)

| Tool | Entry point(s) | Shape |
|---|---|---|
| `run_pipeline.py` | `main(input_dir, output_dir)` | Orchestrates search -> analyze -> check_balances -> filter -> graph. This is the "default auto pipeline" today. |
| `tools/search_wallets.py` | `search_for_wallets(start_path, output_file)` | Walks a directory, writes candidate file list (extension/keyword/coin-name heuristic from `config/search.py`). |
| `tools/analyze_wallets.py` | `analyze_wallet_file(path)`, `analyze_wallets(input_file, output_file)` | Per-file coin/format guess. |
| `tools/check_wallet_balances.py` | `load_service(crypto_name)`, `_check_balance_with_retries(...)`, `check_wallet_balances(input_file, output_file, coins_to_check=None, inconclusive_output=None)` | Balance checks w/ retry; writes `inconclusive_balances.json` sidecar. |
| `tools/filter_wallets.py` | `filter_wallet_balances(input_file, output_file)` | Keeps only non-zero/interesting entries. |
| `tools/build_wallet_graph.py` | `build_relationship_graph(wallet_data)`, `render_graph_report(graph)` | Cross-file relationship graph + Markdown report. |
| `tools/detect_hidden_volumes.py` | `scan_for_hidden_volumes(start_path)`, `render_hidden_volumes_report(candidates)` | Entropy+magic-byte heuristic for VeraCrypt/TrueCrypt-style containers. Detect-and-flag only. |
| `tools/crawl_transaction_graph.py` | `crawl_wallet_cluster(seed_addresses, max_generations=2, max_addresses=200, balance_threshold=1.0, now=None)`, `render_cluster_report(results, ...)`, `load_seed_addresses(arg)` | Public-blockchain co-spend clustering + dormancy. Seeds: single address, literal, or file. |
| `tools/find_seed_phrases.py` | `scan_directory(start_path, max_file_size=...)` | BIP39-checksum-validated seed phrase finder. Phrase text is security-sensitive. |
| `tools/match_seed_phrases.py` | `match_phrases(phrases, num_addresses=5)`, `load_phrases_from_file(path)`, `render_match_report(results)` | Derives addresses from candidate phrases, checks balances. Never exposes private keys; only repeats phrase text for phrases that actually matched a balance. |
| `tools/scan_wallet_dat.py` | `scan_wallet_for_addresses(wallet_path)`, `check_addresses_balances(addresses, limit=None)` | Full Bitcoin Core BDB key enumeration. Structurally never reads private-key bytes. |
| `tools/check_fork_coins.py` | `check_fork_coins_for_addresses(addresses, coins=None)`, `load_addresses_from_file(path)`, `render_fork_coin_report(results, balance_threshold=0.0)` | BCH/BTG balance checks for addresses that held BTC pre-fork. |
| `tools/unlock_wallet.py` | `check_network_status(timeout=2)`, `run_unlock(wallet_path, candidates_file, btcrecover_script=None, allow_online=False)` | BTCRecover wrapper. **Hard offline gate.** Candidates from file only. Relays BTCRecover stdout verbatim (may include the found password). |
| `tools/unlock_exodus_wallet.py` | `extract_exodus_hash(seed_seco_path, ...)`, `run_exodus_unlock(seed_seco_path, candidates_file, script_path=None, allow_online=False)` | hashcat wrapper for Exodus `seed.seco`. Same offline-gate shape as `unlock_wallet.py`. |
| `tools/scan_google_drive.py` | `get_drive_service(...)`, `list_wallet_like_files(service, ...)`, `scan_drive_for_wallets(service, output_dir, query=None)` | OAuth Drive crawl, content flows Drive-server -> local disk directly (never through an AI/session context). |

All 13 tools are already pure-function-callable (not just CLI-shaped) -- every
one exposes an importable function the UI can call directly in-process. No
tool requires re-implementation to be UI-drivable.

## Safety properties already established (must not regress)

1. **Offline gate.** `unlock_wallet.py`/`unlock_exodus_wallet.py` refuse to run
   a real recovery attempt unless the machine is verified offline
   (`check_network_status()` -> `"OFFLINE"`). A Flask dev server bound to
   `127.0.0.1` does not itself require network access, so this gate still
   applies and must be re-checked server-side before every unlock job -- the
   UI must not just hide/disable a button (client-side-only gating is
   trivially bypassed and doesn't protect anything).
2. **Candidates/secrets from file only, never a URL or query string.** The
   existing CLIs read password/seed candidate lists from a file path argument.
   The web UI must preserve "never as a URL parameter or GET-visible value" --
   any textarea/upload flow must write directly to a local temp file server-side
   before invoking the tool, and that file must never appear in a URL.
3. **Never persist found secrets in a durable, easily-stumbled-upon place.**
   Today, `unlock_wallet.py` prints BTCRecover's output (which may include a
   found password) to the CLI's own stdout once, and nothing writes it to a
   log file. A web UI turns "once to stdout" into "held by a server process" --
   the equivalent web-safe behavior is: hold the result in memory for that job
   only, deliver it once via the job-status endpoint, and never write it into
   any persisted job-history JSON/log file on disk.
4. **Never print/return raw private keys.** `scan_wallet_dat.py` and
   `match_seed_phrases.py` already enforce "addresses only" at the function
   level -- the UI layer calling these functions inherits that guarantee for
   free as long as it doesn't independently touch the raw BDB value bytes or
   derived private keys.
5. **Bind to localhost only.** No existing tool talks to anything but public
   blockchain/coin APIs and (for Drive) Google's API -- the new Flask app must
   not listen on `0.0.0.0` by default, since it will be handling wallet files
   and (transiently) unlock candidates.

## Tech stack decision

Flask, not FastAPI. Rationale: this project's existing dependency footprint is
deliberately small (`requests`, `python-dotenv`, `mnemonic`, `bip_utils`,
`google-api-python-client` family) and synchronous -- every existing tool
function is a plain blocking call (network I/O via `requests`, subprocess
calls to BTCRecover/hashcat). FastAPI's value proposition is async
concurrency; nothing here benefits from it, and Flask's dev server plus a
background-thread job runner is enough for a single local user running one
scan/unlock at a time. Frontend: server-rendered Jinja2 templates + a small
amount of vanilla JS (polling a `/api/jobs/<id>` endpoint) -- no frontend
build step, which keeps the later Electron wrap trivial (point Electron's
`BrowserWindow` at `http://127.0.0.1:5000`, no bundler needed).

## Job model

Long-running operations (search, transaction-graph crawl, unlock attempts,
Drive scan) run in a background `threading.Thread`, tracked by an in-memory
job registry (`{job_id: {"status", "result", "error", "started_at"}}`). This
mirrors the existing "run this and check back" shape of the CLI tools and
avoids adding a task-queue dependency (Celery/RQ) that this single-user local
project doesn't need.

## Open questions resolved during design

- **Where does the frontend live?** `web/` at repo root: `web/app.py` (Flask
  app + routes), `web/templates/`, `web/static/`. Keeps the existing
  `tools/`/`services/`/`config/` layout untouched -- the UI is a new consumer
  of those modules, not a restructuring of them.
- **Staging/copy area:** a user-chosen local output directory (defaults to
  `./ui_output/<session>/staged/`), populated via `shutil.copy2` -- copy only,
  never move, so the original drive/files are never touched.
