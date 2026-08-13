# Research Brief: Conservative Balance-Check Failures

## Requirement

North-star `avoid` item: "Avoid negating something completely because an API
couldn't get called enough or timed out" (`.pHive/project-profile.yaml`). Confirmed
live during epic 1's manual smoke test: `check_wallet_balances.py` hit a real
`OKCash` API 500 and an `EthereumService` init failure, both settling on `None`
after exactly one attempt, no retry.

## Codebase findings

- Every `services/*.py` (21 files, sampled `bitcoin.py`, `ethereum.py`,
  `okcash.py`) follows the same shape: `try: request -> if status != 200: return
  None -> except: return None`. **`None` already semantically means "couldn't
  confirm"** — a real `0.0` (confirmed empty address) is a distinct, valid return
  value (`bitcoin.py`: `(funded - spent) / 1e8` can legitimately be `0.0`). So the
  bug isn't ambiguous semantics — it's that `None` is reached after a single
  attempt, and once written to `wallet_balances.json` it's indistinguishable from
  "we tried hard and this really has no confirmed balance."
- `tools/check_wallet_balances.py::check_wallet_balances()` calls
  `service.check_balance(address)` exactly once per address, no retry loop.
- `tools/filter_wallets.py`: `if balance and balance > 0` — both `None` and
  confirmed `0.0` are filtered out identically. This is correct for filter's stated
  purpose (surface wallets *with* money) but means an inconclusive `None` and a
  confirmed-empty wallet vanish into the same silence — there's currently no
  artifact that says "these need a recheck."
- Epic 1's `build_relationship_graph()` already treats `None` balances as a
  first-class, preserved value (not coerced to 0) — so this epic's output stays
  compatible with it as long as `wallet_balances.json`'s shape doesn't change.

## Proposed fix shape (confirmed feasible, no new deps)

Retry `service.check_balance(address)` up to N times (only on `None` results —
services already collapse both HTTP errors and exceptions to `None`, so retrying
on `None` covers both) with a short backoff, **at the orchestration layer**
(`check_wallet_balances.py`), not inside each of the 21 service files. Zero
service-file changes needed — lowest blast-radius option, and the same fix covers
all coins uniformly instead of 21 near-identical hand-edits.

After retries are exhausted, if still `None`, record that `(file, coin, address)`
triple in a **new, separate output file** — a "needs recheck" queue — rather than
letting it disappear. `wallet_balances.json`'s shape and semantics are unchanged
(still `None` = inconclusive), so this is additive, not a breaking change to epic
1's graph builder or `filter_wallets.py`.

## Cross-cutting concerns loaded

`documentation` (only concern defined) — applies: new output file + new retry
behavior need a README update.

## Confidence

High — grounded in direct reads of 3 representative service files, the full
`check_wallet_balances.py`, and `filter_wallets.py`, plus a live reproduction of
the failure mode during epic 1's manual pipeline smoke test.
