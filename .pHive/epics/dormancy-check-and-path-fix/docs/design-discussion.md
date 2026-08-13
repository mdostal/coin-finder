# Design Discussion: Dormancy Check + Standalone-Invocation Fix

**Process note:** same no-live-teammates adaptation as prior epics. Kept
intentionally brief -- this is a small, bounded follow-up on an established
pattern (transaction-graph-crawler), not a new capability class.

## 1. What Are We Doing?

Two small, unrelated-but-bundled fixes:

1. **Standalone invocation bug**: discovered while smoke-testing
   `transaction-graph-crawler` -- every `tools/*.py` that imports `config` or
   `services` fails when run as `python tools/foo.py` (the README-documented
   usage) because Python only puts the script's own directory on `sys.path`,
   not the repo root. Reproduced on `search_wallets.py`, confirming this
   predates recent epics.
2. **Dormancy check**: user request -- "for any wallet, double check it...
   warn you if you claim nothing transferred in 5+ years." Implemented as:
   compute and surface each address's real last-activity timestamp (from
   already-fetched transaction data) so the user can verify their own
   assumptions about a wallet against the actual blockchain record, rather
   than the tool guessing at an unspecified "claimed" date.

## 2. Approach

1. Add a `sys.path.insert(0, ...)` bootstrap (repo root) to every `tools/*.py`
   that imports `config`/`services`: `search_wallets.py`, `analyze_wallets.py`,
   `check_wallet_balances.py`, `build_wallet_graph.py`,
   `crawl_transaction_graph.py`. `filter_wallets.py` and
   `detect_hidden_volumes.py` don't need it (no such imports).
2. `crawl_transaction_graph.py`: add `compute_last_activity_timestamp(txs)` (max
   confirmed `block_time`) and `dormancy_years(timestamp, now=None)`. Cache
   fetched transaction lists during the BFS (`tx_cache`) to avoid re-fetching
   for frontier addresses; only leaf addresses (discovered but never expanded)
   need an extra fetch for their dormancy computation.
3. `render_cluster_report()`: show "last activity N years ago" for every
   address; addresses dormant 5+ years get an explicit call-out phrased as a
   verification prompt ("verify this matches what you expected"), not an
   assertion about what happened.

## 3. What Could Go Wrong

- **low** -- `now` defaults to real time (`time.time()`), injectable for tests.
  No risk in production use; purely a testability concern, already handled.
- **low** -- The sys.path fix changes import behavior for 5 files. Full test
  suite (including the new standalone-invocation test) passing is the
  verification; no behavior change for the actual pipeline flow (`run_pipeline.py`
  already worked before this fix).

## 4. Verification Strategy

```
VERIFICATION PLAN:
  Tools: pytest
  Automated: new tests/test_cli_standalone_invocation.py (subprocess, no
    PYTHONPATH, --help on all 5 affected tools); compute_last_activity_timestamp
    and dormancy_years unit tests; crawl_wallet_cluster dormancy integration test
  Manual: re-ran the real crawler CLI against the actual found address --
    confirmed sensible last-activity output (4.7-8.5 years across the cluster)
  Not verifying: nothing new -- same substrate as prior epics
```

## 5. Scale Assessment

```
SCALE ASSESSMENT:
  Files affected: 6 (5 tools/*.py path-fix, 1 crawl_transaction_graph.py
    dormancy addition) + README.md
  RECOMMENDATION: Proceed to a single combined story (both changes are small
    and were developed together in one sitting)
```
