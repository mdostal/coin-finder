# Research Brief: Group-View Transaction Graph

**Process note:** self-authored during a live `/loop` session directly following
extensive hands-on work on the exact code this epic touches (findings/crawl
wiring shipped as v0.33.0 minutes before this plan run) -- no separate
researcher dispatch; same no-live-teammates adaptation as `transaction-graph-
crawler` and `wallet-relationship-graph`.

## What already exists

- **`tools/crawl_transaction_graph.py`** (epic `transaction-graph-crawler`):
  `crawl_wallet_cluster(seed_addresses, max_generations=2, max_addresses=200,
  balance_threshold=1.0, now=None)` returns `{address: {"confidence":
  "seed"|"co-spend"|"output", "generation": int, "balance": float|None,
  "last_activity_timestamp": int|None, "dormant_years": float|None}}`.
  Bitcoin-only (Blockstream API). `render_cluster_report(results,
  balance_threshold)` renders it as sorted plain text.

- **`web/app.py`'s `_run_crawl_job(addresses)`** (lines ~754-773): the route
  handler behind `/item/crawl`. Writes a temp seed-addresses file, calls
  `load_seed_addresses` + `crawl_wallet_cluster`, records every discovered
  address back into `findings.db` via `record_finding("Bitcoin", address,
  info.get("balance"), source_label="crawl_transaction_graph")`, and returns
  `{"report": ..., "results": ...}` as the job's result -- **never persisted
  beyond the in-memory job registry** (`web/jobs.py`'s `_jobs` dict, gone on
  app restart, and already stripped from the polling API once the job reaches
  a terminal state if it were ever marked `secret=True`, which this one is
  not, so it's readable via `/item-result/<job_id>` until the process exits,
  but nowhere after that).

- **`web/findings.py`**: sqlite-backed (`findings.db` under `app_data_dir()`),
  schema `(coin, address, balance, source_path, source_label, status,
  first_seen_at, last_checked_at, watched, watch_note)`, `PRIMARY KEY (coin,
  address)`. `record_finding` upserts on that key -- it has NO concept of
  "which crawl run(s) found this address" or "what cluster/generation/
  confidence it was discovered at." A crawl run's *edges* (which seed
  produced which discovery, at what confidence/generation) are thrown away;
  only the flattened *address+balance* survives, indistinguishable from a
  finding that came from a plain file-system scan.

- **`web/templates/findings.html`** (rewritten this session, v0.33.0): every
  Bitcoin finding gets a "Graph" button (`POST /item/crawl` with
  `addresses=<that one address>`) and a bulk-select "Graph selected" toolbar
  action. Both routes reuse `_run_crawl_job` unchanged.

- **Migration precedent**: `web/findings.py` already has a real
  `_MIGRATIONS` list (`ALTER TABLE ... ADD COLUMN`, try/except
  `OperationalError` = already-migrated) added this session for the
  `watched`/`watch_note` columns on a pre-existing db. The same pattern
  applies directly to a new crawl-runs table/db.

- **`web/paths.py`'s `app_data_dir()`**: the established local-storage root
  (`~/Library/Application Support/coin-finder/` when frozen, repo-relative
  `web/` dir otherwise). `findings.db` lives here; a new `crawl_runs.db`
  should too, for the same frozen-build persistence guarantee.

## The gap this epic closes

Nothing currently answers: *"Did crawling wallet A's cluster and crawling
wallet B's cluster (found on different drives, at different times) both
surface some third address C?"* That's the actual signal the user is after --
address C showing up as a "relative" of two independently-found wallets is
much stronger evidence of common ownership than either crawl alone, and is
exactly the kind of thing that should reprioritize which physical drive to
dig through next.

`web/build_wallet_graph.py`-family tooling from `wallet-relationship-graph`
(pipeline stage 5, `tools/build_wallet_graph.py`) is a different mechanism --
it correlates addresses found *within a single scan's* discovered wallet
files (regex/pattern matches co-occurring in the same file set), not
addresses discovered by separate *transaction-graph crawl runs* over time.
No overlap; this epic is additive.

## Constraints carried in from this session (must follow)

- Local-only storage under `app_data_dir()`, sqlite, same shape as
  `findings.py` (`_connect`, `_SCHEMA`, `_MIGRATIONS` pattern).
- Every `requests.*()` call needs `timeout=` on the same line
  (`tests/test_no_unbounded_network_calls.py` enforces this statically) --
  N/A here, this epic adds no new network calls, it persists results an
  *existing* network-calling function already produced.
- Every `subprocess.run()` to an external CLI needs `stdin=subprocess.DEVNULL`
  + a timeout -- N/A, no new subprocess calls.
- Jinja templates: `{% import "_macros.html" as m with context %}`, not a
  bare import (silently breaks `nav_groups`/`active_nav_group`).
- Full `pytest tests/` and `cd src-tauri && cargo test` must stay green.
- Version bump touches all four of `web/_version.py`,
  `src-tauri/tauri.conf.json`, `src-tauri/Cargo.toml`, `package.json`, plus a
  `CHANGELOG.md` entry, then PyInstaller sidecar rebuild + `npm run
  tauri:build` + `gh release create`.
