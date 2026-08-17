# Design Discussion: Blockchain Transaction-Graph Crawler

**Process note:** same no-live-teammates adaptation as prior epics.

## 1. What Are We Doing?

Given a known Bitcoin address (e.g. the 0.3 BTC find), crawl outward through the
public blockchain transaction graph to discover other addresses that likely
belong to the same person -- specifically to find "sitting" wallets that received
funds from mining/transfers and were never spent. Public data only, no private
keys. Bitcoin-only for v1 (transaction-graph structure is coin-specific; other
coins are a follow-up).

## 2. What I Found

See research-brief.md. Key decision: use common-input-ownership clustering
(high-confidence, cheap) as the primary signal, plus bounded output-following
(lower-confidence, fan-out-capped) for the "where did it go" direction. Reusing
`services/bitcoin.py`'s `BitcoinService` for balance checks on discovered
addresses -- no new balance-check logic needed, just new address *discovery*.

## 3. My Proposed Approach

1. **`tools/crawl_transaction_graph.py`**:
   - `fetch_address_transactions(address)` -- GET the Blockstream `/txs` endpoint,
     returns raw tx list (up to 25 recent). Reuses the retry pattern from
     `check_wallet_balances.py` (`_check_balance_with_retries`-style: retry on
     None/error, never on a real empty result).
   - `find_co_spend_addresses(tx, known_address)` -- returns the set of other
     input addresses when `known_address` appears in `tx["vin"]` (i.e. it was
     spent from in this tx). High confidence.
   - `find_output_addresses(tx, known_address, max_outputs=20)` -- returns output
     addresses only when `known_address` is an input on `tx` AND
     `len(tx["vout"]) <= max_outputs` (skip mining-pool/exchange-shaped
     high-fanout transactions -- the exact pattern observed in real data).
     Lower confidence, tagged as such.
   - `crawl_wallet_cluster(seed_addresses, max_generations=2, max_addresses=200,
     balance_threshold=1.0)` -- BFS orchestrator: for each generation, fetch txs
     for the current frontier, discover co-spend (always) and bounded-output
     (capped) addresses, stop discovering new addresses once `max_addresses` is
     reached (existing frontier still finishes its current generation). After the
     crawl, check balance (via `BitcoinService`) for every discovered address.
     Returns `{address: {confidence, generation, balance}}`.
   - `render_cluster_report(results, balance_threshold)` -- readable summary,
     sorted by balance descending, addresses at/above `balance_threshold` called
     out as significant.
2. **CLI**: `python tools/crawl_transaction_graph.py <seed_address>
   <output_file> [--generations N] [--max-addresses N] [--threshold BTC]` --
   writes JSON results + sibling `.md` report (same two-output convention as
   epics 1 and 3).
3. **Not wired into `run_pipeline.py`** -- standalone, deliberately invoked
   against a specific known address, same reasoning as `detect_hidden_volumes.py`.
4. **Tests**: mock `fetch_address_transactions` and `BitcoinService.check_balance`
   with small hand-built fixtures matching the real API shape (verified live
   against the actual found address in research) -- no real network calls in the
   test suite.

## 4. What Could Go Wrong

- **high** -- Even with the co-spend/output-cap heuristics, a busy address could
  still discover a lot of addresses. `max_addresses` is a hard safety cap;
  reaching it is reported explicitly (never silent truncation), consistent with
  workflow-authoring conventions this project already follows.
- **medium** -- Output-following can still misattribute a genuine payment-to-
  someone-else as "same owner." Every output-derived address is tagged
  `confidence: output` (vs `confidence: co-spend`) in the results and report, so
  the user can weight them accordingly -- never presented as equally certain.
- **low** -- Blockstream's `/txs` endpoint returns only the 25 most recent
  confirmed transactions per call (no pagination in v1). An address with a long
  history won't be fully covered. Stating this explicitly rather than silently
  under-covering; deeper pagination (`/txs/chain/:last_seen_txid`) is a
  reasonable follow-up if it turns out to matter.

## 5. Dependencies and Constraints

- No new dependencies -- `requests` already in `requirements.txt`.
- Reuses `services/bitcoin.py::BitcoinService` for balance checks (no
  duplicated balance logic).
- Bitcoin-only in v1 -- other coins' block explorer APIs have different
  transaction-graph shapes; out of scope here.

## 6. Open Questions

1. Defaults: `max_generations=2`, `max_addresses=200`, `balance_threshold=1.0`
   BTC. You mentioned "sitting with 5+" -- I'm defaulting the *report
   highlight* threshold lower (1.0 BTC) so smaller-but-real balances don't get
   hidden, while still visually calling out anything at 5+ as especially
   notable. Reasonable, or would you rather tune these?

## 7. Verification Strategy

```
VERIFICATION PLAN:
  Tools: pytest (existing dev dependency)
  Platforms: N/A
  Automated: find_co_spend_addresses(), find_output_addresses(), and
    crawl_wallet_cluster() via small hand-built tx fixtures (shaped like the
    real Blockstream response, verified live) and a mocked BitcoinService --
    no real network calls in the test suite
  Manual: run the real CLI against the actual found address
    (1GcWwQTb4giriXRmEjdizaXnyy5ABpKCpB) to confirm real-world output is sane
    -- this is the only way to validate the heuristic against real transaction
    shapes (including the observed 100+-output transactions)
  Not verifying: coins other than Bitcoin (out of scope, see Dependencies)
```

## 8. Scale Assessment

```
SCALE ASSESSMENT:
  Files affected: ~3 (new tools/crawl_transaction_graph.py, new
    tests/test_crawl_transaction_graph.py, README.md edit)
  Subsystems: 1 (Python stdlib + requests, reuses services/bitcoin.py)
  Migration required: no
  Cross-team coordination: no
  Unknowns: 1 (threshold defaults, non-architectural)

  RECOMMENDATION: Proceed to stories
  RATIONALE: Same shape as prior epics -- single layer, small file count,
    reuses existing balance-check service. Small scope.
```
