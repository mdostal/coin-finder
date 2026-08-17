# Design Discussion: Wallet & Coin Relationship Graph

**Note on process:** this design discussion was produced without a live multi-agent
review team (no CC-Workflows/Multica dispatch configured, no additional personas
available in this session) — I wrote it directly and I'm grilling it myself below
instead of via a separate `tpm` persona. Flagging the adaptation once, per the
project's `hive.config.yaml → planning.collaborative_review: true` intent, rather
than silently skipping the ceremony.

## 1. What Are We Doing?

Today, `check_wallet_balances.py` and `filter_wallets.py` treat every `(file,
address)` pair in isolation. If the same seed phrase got backed up to three
different files, or one file is an Exodus multi-coin backup that yielded BTC and
ETH addresses but nothing else, the pipeline has no way to tell you that. The user
(and hobbyist users) explicitly said this is a pain point: "no way to visualize/graph
relationships between wallets and coins to spot ones still missing"
(`.pHive/project-profile.yaml → north_star.pain_points`).

"Done" for this epic means: after running the existing pipeline through the
check-balances stage, a new stage reads `wallet_balances.json` (or
`wallet_analysis.json` if balances haven't been checked) and produces a relationship
graph that surfaces two concrete signals:

1. **Duplicate addresses across files** — the same address found in ≥2 files is
   strong evidence it's a real wallet, not a false positive.
2. **Coverage gaps in multi-coin files** — a file that yielded addresses for some
   coins but not others is worth a second look; the user can decide whether to dig
   further (e.g. re-run with a wider `MAX_FILE_SIZE`, or manually inspect for coins
   the pipeline doesn't have a service/pattern for yet).

Not in scope: HD-wallet address derivation, a real UI (that's a separate, later
north-star item), and encrypted-volume detection (a separate epic candidate).

## 2. What I Found

- `tools/analyze_wallets.py` → `wallet_analysis.json`:
  `{file_path: {crypto_name: [address, ...]}}` — this is the natural join key: same
  `address` value appearing under different `file_path` keys is a duplicate.
- `tools/check_wallet_balances.py` → `wallet_balances.json`:
  `{file_path: {crypto_name: {address: balance}}}` — richer, includes balance, so
  preferred input when available (lets us weight/annotate graph nodes by balance).
- `run_pipeline.py` already threads stage outputs through `<output_dir>/checks/*` —
  a new stage slots in the same way: read one JSON, write another, print a status
  line. `tools/filter_wallets.py` (30 lines) is the closest template: single
  responsibility, thin argparse wrapper, no class hierarchy needed.
- `services/__init__.py`'s `WalletService` base class is irrelevant here — this
  stage does no API calls, so it doesn't need a per-coin service.
- No test suite exists anywhere (`code_quality.test_first_signals.test_absence:
  true`). `hive.config.yaml → execution.default_methodology: tdd`, so this is the
  first code in the repo landing with tests — I want the test file structure here to
  be one other contributors would naturally extend (`tests/test_<module>.py`,
  `pytest`, since `pytest` is the de facto standard and needs no new runtime dep —
  it's a dev-only dependency).
- `requirements.txt` has only `requests` + `python-dotenv`. README explicitly
  distrusts unvetted third-party libraries. I'm keeping the graph builder itself
  stdlib-only (`json`, `collections.defaultdict`, `argparse`).

## 3. My Proposed Approach

1. **New module `tools/build_wallet_graph.py`** with a pure function
   `build_relationship_graph(wallet_data: dict) -> dict` that takes the
   `wallet_balances.json` (or `wallet_analysis.json`) shape and returns a graph dict:
   ```
   {
     "nodes": {"files": [...], "addresses": [...], "coins": [...]},
     "edges": {"file_has_address": [...], "address_is_coin": [...]},
     "signals": {
       "duplicate_addresses": {address: [file_path, ...]},   # len >= 2
       "multi_coin_files": {file_path: [coin, ...]},          # len >= 2
       "coverage_gaps": {file_path: {"found": [...], "missing_supported_coins": [...]}}
     }
   }
   ```
   `coverage_gaps` is deliberately conservative for v1: "missing_supported_coins" is
   just "coins this tool supports (`config/wallet.py::WALLET_SERVICES`) that weren't
   found in this file" — not a claim the wallet *has* those coins. That's a nudge for
   the user to double-check, not an assertion.
2. **CLI entry point** in the same file (`if __name__ == "__main__"`), same shape as
   `filter_wallets.py`: `python tools/build_wallet_graph.py <input_file>
   <output_file>`.
3. **Human-readable report**: a second function `render_graph_report(graph: dict) ->
   str` that writes a plain-text/Markdown summary (duplicate addresses first —
   highest signal — then multi-coin files, then coverage gaps) to
   `<output_dir>/wallet_relationships.md`. No new UI/viz dependency; this is the
   "simple UI" north-star item's precursor, not its fulfillment.
4. **Pipeline integration**: add this as a fifth stage in `run_pipeline.py`, after
   `filter_wallet_balances` (so it can use the richest, balance-annotated data) —
   pass it `scan_output` (`wallet_balances.json`, pre-filter) rather than
   `filter_output`, since duplicate/coverage signals are still useful even for
   zero-balance addresses.
5. **Tests**: `tests/test_build_wallet_graph.py` — pure unit tests against
   `build_relationship_graph()` with small hand-built `wallet_data` dicts (no file
   I/O, no network). This is also the first `tests/` directory in the repo.
6. **README update**: extend the "Pipeline Overview" section and file-structure tree
   with the new stage (the `documentation` cross-cutting concern applies here).

## 4. What Could Go Wrong

- **medium** — `coverage_gaps` could read as an overclaim ("this file HAS these
  coins") if the report wording isn't careful. Mitigating by naming the field
  `missing_supported_coins` and writing the report copy as a question, not a
  finding.
- **medium** — Large wallet-balance JSON files (multi-TB drive scans) could make an
  in-memory `defaultdict`-based graph slow or memory-heavy. For v1 I'm accepting
  this — the existing pipeline already loads the whole JSON into memory in
  `check_wallet_balances.py` and `filter_wallets.py`, so this isn't a new
  scalability ceiling, just an existing one this stage inherits. Worth a follow-up
  epic if it becomes a real bottleneck (ties into the "deep-crawl multi-TB drives"
  north-star item, which is out of scope here).
- **low** — `balance` can be `None` (API failure, not "zero") per
  `check_wallet_balances.py`. The graph signals must not treat `None` as "no
  balance" — that's the exact "don't negate on a flaky API call" north-star
  `avoid` item, just showing up in a different tool. I'll carry `balance` through
  as-is (including `None`) rather than coercing it.

## 5. Dependencies and Constraints

- No external dependencies — stdlib only.
- No blocking dependency on other epics; this can run standalone against existing
  pipeline output.
- Soft dependency: richer results if run after `check_wallet_balances.py` (has
  balances) rather than just `analyze_wallets.py` (addresses only) — the function
  signature supports either shape since `check_wallet_balances`'s nested `{address:
  balance}` is a superset shape of `analyze_wallets`'s `[address, ...]` list; I'll
  normalize both to a common internal shape at the top of
  `build_relationship_graph()`.

## 6. Open Questions

1. Should `build_wallet_graph` run automatically as part of `run_pipeline.py` by
   default, or only via its standalone CLI? I'm proposing "automatic, as stage 5" in
   §3 — flag if you'd rather keep it opt-in (e.g. behind a `--graph` flag) since it
   adds a bit of runtime to every pipeline run.
2. For `coverage_gaps`, is "coins we support but didn't find in this file" the right
   v1 signal, or would you rather I only flag it when the file also matched
   wallet-related keywords/extensions strongly enough to suggest a real multi-coin
   wallet app (e.g. Exodus, Trust Wallet) — i.e. a higher-precision, lower-recall
   version? I went with the simpler version for v1.

## 7. Verification Strategy

```
VERIFICATION PLAN:
  Tools: pytest (new dev dependency — first test tooling in the repo)
  Platforms: N/A (CLI/stdlib only, no platform-specific code)
  Automated: build_relationship_graph() and render_graph_report() — unit tests
    against hand-built wallet_data fixtures covering: duplicate address across 2
    files, multi-coin file, coverage gap, and a None-balance address (must not be
    treated as zero/negated)
  Manual: run_pipeline.py end-to-end integration (visually confirm
    wallet_relationships.md reads sensibly) — no existing pipeline integration
    tests to extend, and standing up a full fixture wallet directory is
    disproportionate for this epic
  Not verifying: performance at multi-TB scale (explicitly deferred, see §4)
```

## 8. Scale Assessment

```
SCALE ASSESSMENT:
  Files affected: ~4 (new tools/build_wallet_graph.py, new
    tests/test_build_wallet_graph.py, run_pipeline.py edit, README.md edit)
  Subsystems: 1 (pipeline tools — Python only, no cross-stack/cross-service work)
  Migration required: no
  Cross-team coordination: no (solo project)
  Unknowns: 2 (see Open Questions above — both are scope-shape, not
    architecture-changing either way)

  RECOMMENDATION: Proceed to stories
  RATIONALE: Single layer, single language, small file count, no data migration,
    no cross-stack coordination. This is a Small-scope change per the routing
    rubric (design discussion gives sufficient context) — H/V planning would be
    ceremony without payoff here.
```
