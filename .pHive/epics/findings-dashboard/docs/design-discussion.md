# Design Discussion: findings-dashboard

## Goal

A persistent, aggregated inventory of every wallet/address/balance ever
found across every scan this project has run -- not just one job's
in-memory result, gone the moment the server restarts. Directly requested:
"a dashboard where this will show all the wallets and the amounts and
stuff so we can basically move and archive all the 0s and then work on
the rest until we are fully complete... this matters quite a bit when we
do the very sporadic search across the largest drives." The upcoming
Google Drive and physical-drive crawls will span many separate scan runs
over many sessions -- without a persistent store, there is no way to see
the accumulated picture across all of them, and no way to mark
zero-balance findings as reviewed so they stop cluttering the view of
what still needs attention.

## Approach

**Storage: SQLite**, not another JSON file. This is the first genuinely
relational, growing, queryable dataset in this project (every prior local
state file -- bound targets, mounts -- was a small, rarely-touched list;
findings will accumulate into the thousands across a real multi-drive
crawl and need sorting/filtering/status updates). `web/findings.db`
(gitignored, local runtime state, same category as `bound_targets.json`).

Schema: one `findings` table, keyed by `(coin, address)` so re-scanning
the same address updates it in place rather than duplicating:

```sql
CREATE TABLE findings (
  coin TEXT NOT NULL,
  address TEXT NOT NULL,
  balance REAL,              -- NULL = inconclusive, never conflated with 0
  source_path TEXT,          -- wallet file / directory this came from
  source_label TEXT,         -- human label, e.g. "Desktop scan 2026-08-13"
  status TEXT NOT NULL DEFAULT 'new',  -- new | archived
  first_seen_at REAL NOT NULL,
  last_checked_at REAL NOT NULL,
  PRIMARY KEY (coin, address)
);
```

`web/findings.py`: `record_finding(coin, address, balance, source_path,
source_label)` (upsert -- updates `balance`/`last_checked_at` on an
existing row, preserves `status` so a manual archive isn't undone by a
later re-scan), `list_findings(include_archived=False)`, `archive(coin,
address)` / `unarchive(coin, address)`, `archive_all_zero_balance()`.

**Wiring, not reimplementation.** Every job that already produces
balance-bearing results (`_run_scan_job`, `_run_scan_wallet_dat_job`,
`_run_crawl_job`, `_run_fork_coins_job`) gets one additional call at the
end: feed its results into `record_finding()`. No scan/check logic is
duplicated -- the findings store is a side-effect recorder, not a new
data source.

**New `/findings` page**: one table, every coin/address/balance/status,
sortable, a "hide archived" toggle (default on), and a one-click "archive
all zero-balance" action -- directly the "move and archive all the 0s"
workflow requested. An "Unlock" / "Extract key" quick-link per row where
the address's source wallet file is known, so acting on a promising
finding doesn't require re-navigating from scratch.

## Risks

- **Findings accumulate real addresses/balances in a durable local file**
  -- not secret in the same sense as a private key (a public address and
  its balance are already public blockchain data), but still real
  personal financial data worth keeping local-only. Mitigation: gitignored
  like every other local runtime state file; no new exposure beyond what
  the existing per-job JSON outputs already had, just made persistent and
  aggregated instead of scattered/transient.
- **A stale `last_checked_at` could mislead** ("this shows 0, but that
  was 6 months ago before a fork-coin's balance changed"). Mitigation:
  `last_checked_at` is always shown on the dashboard, not hidden --
  consistent with this project's "never silently conflate inconclusive/
  stale with confirmed-empty" discipline.

## Scope

**Two stories**: (1) the storage layer + wiring into existing jobs, (2)
the dashboard page + archive actions. Small enough to not warrant full
H/V ceremony -- same condensed treatment as this session's smaller,
well-understood epics.
