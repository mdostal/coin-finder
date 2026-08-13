# Design Discussion: Conservative Balance-Check Failures

**Process note:** same adaptation as epic 1 — no live multi-agent teammates in
this session, so this is a direct self-authored pass, self-grilled, rather than a
separate persona review. Noted once for provenance.

## 1. What Are We Doing?

`check_wallet_balances.py` gives up on an address after exactly one failed API
call and writes `None`, which then reads identically to "confirmed empty" once
filtered. This directly violates the north-star `avoid` item: don't negate a
wallet just because an API call was flaky. Done = retries happen before giving
up, and addresses that are *still* inconclusive after retries land in a visible
"needs recheck" file instead of silently vanishing.

## 2. What I Found

See `docs/research-brief.md`. Key points: `None` already means "inconclusive" in
every service's contract (confirmed via `bitcoin.py`, `ethereum.py`,
`okcash.py`); the fix belongs in `check_wallet_balances.py`'s orchestration loop,
not the 21 service files, since retrying the existing `check_balance(address)`
call covers every coin uniformly with zero service-file edits. Epic 1's graph
builder already treats `None` as a preserved value, so this stays compatible.

## 3. My Proposed Approach

1. In `tools/check_wallet_balances.py`, wrap the existing
   `service.check_balance(address)` call in a small retry helper:
   `_check_balance_with_retries(service, address, max_retries=3,
   backoff_seconds=2)`. Only retries when the result is `None` — a confirmed
   float (including `0.0`) returns immediately, no wasted calls.
2. Track every `(file_path, crypto_name, address)` triple whose *final* result
   (after retries exhausted) is still `None` in an `inconclusive` list.
3. After the main loop, if `inconclusive` is non-empty, write it to a new
   sibling file (default `inconclusive_balances.json` next to `output_file`,
   overridable via a new optional `inconclusive_output` parameter — backward
   compatible, existing callers unaffected).
4. `run_pipeline.py`: one line — print the inconclusive-file path when it's
   non-empty, so it's visible in normal pipeline runs, not just to someone who
   reads the code.
5. Tests: `time.sleep` gets patched out in tests (no real delays); cover
   immediate-success (no retry needed), eventual-success (fails then succeeds),
   and exhausted-retries (stays `None`, lands in inconclusive list).
6. README: document the new retry behavior and `inconclusive_balances.json`.

## 4. What Could Go Wrong

- **medium** — Retries make the pipeline slower against real flaky/rate-limited
  APIs (up to 3x calls per address on failure, plus backoff sleep). Accepting
  this deliberately — it's the entire point of the north-star ask (thoroughness
  over speed for a personal recovery tool), but flagging it as a real, felt
  tradeoff.
- **low** — Retrying on `None` doesn't distinguish "rate limited, will succeed on
  retry" from "genuinely invalid address, will always 4xx." Services don't
  currently expose status codes to the caller, only `None`, so finer-grained
  retry logic (skip retry on 4xx) isn't possible without touching all 21
  services — deliberately out of scope for this epic; accepting some wasted
  retries against permanently-invalid addresses as the cost of the simpler,
  lower-blast-radius fix.
- **low** — `backoff_seconds=2` between up to 3 attempts adds up across many
  addresses/coins on a large scan. Not tuning this precisely in v1; it's a
  constant at the top of the file, trivially adjustable later.

## 5. Dependencies and Constraints

- No new dependencies — `time.sleep` is stdlib.
- No dependency on epic 1's code; only a shared-output-shape compatibility
  constraint (`wallet_balances.json`'s per-address value stays `None | float`,
  unchanged), verified by re-running epic 1's `build_relationship_graph` tests
  after this epic lands.

## 6. Open Questions

1. `max_retries=3, backoff_seconds=2` — reasonable defaults, or would you rather
   retries be configurable via a CLI flag / env var? Going with hardcoded
   constants for v1 (matches the project's existing `config/search.py`-style
   constants pattern) — easy to promote to a flag later if it turns out to
   matter.

## 7. Verification Strategy

```
VERIFICATION PLAN:
  Tools: pytest (existing dev dependency from epic 1)
  Platforms: N/A
  Automated: _check_balance_with_retries() and check_wallet_balances()'s
    inconclusive-tracking, via a fake WalletService test double (no real network
    calls) covering: immediate success, eventual success after N failures,
    exhausted retries -> inconclusive file
  Manual: none planned — this is fully unit-testable via a fake service double,
    unlike epic 1's pipeline-wiring story which needed a manual end-to-end pass
  Not verifying: real third-party API retry/backoff behavior under actual rate
    limiting (would require live API credentials and time; out of scope)
```

## 8. Scale Assessment

```
SCALE ASSESSMENT:
  Files affected: ~3 (tools/check_wallet_balances.py, run_pipeline.py, new
    tests/test_check_wallet_balances.py) + README.md
  Subsystems: 1 (pipeline tools, Python only)
  Migration required: no
  Cross-team coordination: no
  Unknowns: 1 (see Open Question above — a config-shape question, not
    architecture-changing)

  RECOMMENDATION: Proceed to stories
  RATIONALE: Same shape as epic 1 -- single layer, small file count, additive
    output (no breaking shape changes). Small scope.
```
