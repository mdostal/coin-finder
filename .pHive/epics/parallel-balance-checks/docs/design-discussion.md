# Design Discussion: Parallel Balance Checks

**Process note:** same no-live-teammates adaptation as every epic this
session. First of a 3-epic technical track requested directly: "The
balance checks are also pretty trash as it can parallelize them and
doesn't need to do the 1/5-10s bullshit. Each org has it's own and can be
running at the same fucking time." The other two epics in this track
(visual transaction graph, scan exclude-list) follow after this one ships.

## 1. What Are We Doing?

`tools/check_wallet_balances.py`'s `check_wallet_balances()` is fully
serial today: one address at a time, across every coin, across every
file, each with up to 3 retries at a 2s backoff on failure. With ~1000+
addresses in a real wallet.dat (the Armory-style BDB enumeration mentioned
in project history) this is the literal "1/5-10s bullshit" -- minutes to
hours for one file, even though the ~21 configured coin services
(`services/*.py`, one class per coin, each hitting a distinct external
API/"org") have nothing to do with each other and could run fully
concurrently.

## 2. What I Found

- `check_wallet_balances()` (`tools/check_wallet_balances.py:61`) loops
  `file_path -> crypto_wallets -> crypto_name -> addresses`, calling
  `_check_balance_with_retries()` synchronously for every single address,
  in one thread, regardless of which coin/service it belongs to.
- `services/__init__.py`'s `REQUEST_TIMEOUT_SECONDS = 15` is already
  enforced per-call (each service's own `check_balance()` passes it to
  `requests.get`) -- concurrency doesn't need to touch that at all, each
  thread's calls already time out independently.
- Every coin's service is a distinct class hitting a distinct external
  host (`config/wallet.py`'s `WALLET_SERVICES` maps 21 coins to 21
  separate `services/*.py` modules) -- there is no shared rate limit or
  shared connection to serialize across coins, only within one coin's own
  API (which the existing per-address retry/backoff already respects).
- `tests/test_check_wallet_balances.py` has a hard assertion on exact
  ordered progress-callback output
  (`test_progress_callback_invoked_once_per_address` expects
  `[(1, 2), (2, 2)]`) -- but every existing test only ever passes ONE coin
  in `coins_to_check`. A worker-per-coin design preserves this exactly:
  with one coin there is exactly one worker thread, so behavior for every
  existing test is byte-identical, no test rewrites needed.

## 3. My Proposed Approach

Restructure `check_wallet_balances()` around one worker **per coin**, not
per address: for each coin present in `coins_to_check` (and present in
the input data), spin up a `concurrent.futures.ThreadPoolExecutor` task
that processes that coin's addresses -- across every file that has any --
sequentially, in original order, exactly as today. Different coins' tasks
run concurrently; each coin still gets one clean, ordered, backoff-
respecting stream of calls against its own API. `max_workers` = number of
distinct coins being checked (at most ~21, trivially safe for I/O-bound
threads).

Thread-safety, minimal surface:
- Every `results[file_path] = {}` entry is pre-created before any worker
  starts (file paths are known upfront from the input JSON) -- workers
  then only ever write to their own coin's key inside an already-existing
  per-file dict, never racing on dict creation.
- `checked_count` (for `progress_callback`) becomes a small
  `threading.Lock`-guarded counter -- the only genuinely shared mutable
  state, since `+= 1` is not atomic.
- `inconclusive` accumulation and `progress_callback` invocation happen
  under the same lock as the counter increment, so a caller's callback
  never sees two calls for the same `current` value or an inconsistent
  `total`.

Function signature is unchanged -- `check_wallet_balances(input_file,
output_file, coins_to_check=None, inconclusive_output=None,
progress_callback=None)` -- this is an internal concurrency change, not
an API change. Every existing call site (CLI, `web/app.py`'s three job
functions) needs zero changes.

## 4. What This Does NOT Change

- `_check_balance_with_retries()` -- reused unmodified, still the unit of
  work per address, still respects `MAX_BALANCE_RETRIES`/
  `RETRY_BACKOFF_SECONDS`.
- Per-service `check_balance()` implementations -- untouched. No new
  intra-service concurrency (a single coin's own addresses still run one
  at a time, in order) -- the ask was cross-org parallelism, not hammering
  one API harder.
- Output file shape (`wallet_balances.json`/`inconclusive_balances.json`)
  -- byte-identical structure, just assembled concurrently instead of
  sequentially. Address-level ordering *within* a coin is preserved;
  ordering *across* coins in the final dict is whatever `dict` insertion
  order the concurrent completions produce (never asserted on by existing
  tests, which are all single-coin).

## 5. Risks

- **Thread-safety bugs are the main risk class here** -- mitigated by
  keeping the shared-mutation surface to exactly one lock guarding one
  counter + one callback invocation, and by every other piece of state
  either being coin-exclusive (each worker only ever writes its own
  `results[file_path][coin]` and `inconclusive[file_path][coin]` keys) or
  pre-created before threading starts.
- **A new flaky-timing test risk**: proving genuine concurrency (not just
  "the code compiles") needs a test that two coins' service calls
  actually overlap in wall-clock time -- using a `threading.Event` to
  synchronize two mock services (each blocks until the other has started)
  is the standard, non-flaky way to assert this, not a sleep-and-hope
  timing test.

## 6. Scale Assessment

**Small.** One function's internals restructured, no new files, no
signature/output changes. One story.
