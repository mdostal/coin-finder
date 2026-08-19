# Structured Outline: Scalable Scan Engine

Builds on `design-discussion.md` (goal, scope, confirmed decisions) and
`horizontal-plan.md` / `vertical-plan.md` (layers, slice order). This
document details the concrete technical approach per slice, the full file
manifest, the risk registry, and the planning team's elicitation stress-test.

## Part 1: Detailed Approach

### 1.1 Shared checkpoint store (`tools/checkpoint_store.py`, new)

A generic, reusable sqlite-backed class every stage below is built on.

```python
class CheckpointStore:
    def __init__(self, checkpoint_path, run_key: dict):
        # Opens sqlite with WAL mode + a real busy_timeout (e.g. 5000ms) --
        # today's zero explicit WAL/timeout anywhere in the repo is exactly
        # the gap that makes real multi-process writers risky.
        # run_key (e.g. {"start_path": ...} for search, {"input_file": ...}
        # for analyze/check_balances) is compared against a stored `meta`
        # row on open -- a mismatch means "different run," and the store
        # resets its completed_units table rather than reusing stale state
        # (same behavior as tonight's search checkpoint, generalized).

    def is_completed(self, unit_id: str) -> bool: ...
    def mark_completed(self, unit_id: str): ...      # buffered in memory
    def flush(self): ...                              # commits buffered marks in one transaction
    def count_completed(self) -> int: ...              # SQL COUNT, never loads all ids into Python
    def is_paused(self) -> bool: ...                   # reads a single meta row
    def request_pause(self): ...                       # sets the meta row (called from the pause route)
    def clear_pause(self): ...
    def close(self): ...
    def delete(self): ...                               # removes the file on clean completion
```

`unit_id` is deliberately opaque to the store — a directory path (search), a
file path (analyze), or a composite `f"{coin}|{file_path}|{address}"`
(check_balances). The store never needs to know what a unit *means*, only
whether it's done — this is what makes one module serve four different
stages instead of four bespoke formats.

**Migration note:** `search_wallets.py`'s already-shipped sqlite checkpoint
(tonight, v0.53.6) gets refactored to call this extracted module instead of
its inline `_open_checkpoint_db`/`_is_dir_completed`/`_count_completed_dirs`
helpers — behavior-preserving, proven by the existing test suite for that
file continuing to pass unchanged.

### 1.2 Analyze: resume + multiprocessing (`tools/analyze_wallets.py`)

Today: sequential `for file_path in file_paths`, whole-file-in-memory regex
matching, no checkpoint parameter exists at all.

New design:
- Add `checkpoint_path=None` parameter, backed by `CheckpointStore` keyed on
  `{"input_file": search_output_path}`.
- Replace the sequential loop with `multiprocessing.Pool(processes=N)`
  (`N` from the new resource-control setting, §1.6). Each worker calls a
  module-level, picklable `_analyze_one_file(file_path) -> (file_path,
  results_or_None)` — pure function, no shared state, so no new lock
  contention inside the worker.
- **`scan_index.py` (the existing content-hash dedup cache) writes stay in
  the main process only.** Workers return their analysis result; the main
  process (consuming `pool.imap_unordered`) does the `record_scanned_file`
  write and the `checkpoint_store.mark_completed(file_path)` call together,
  in the same loop that already exists for progress reporting. This avoids
  introducing concurrent writers to `scan_index.db` entirely, rather than
  adding WAL/locking there too.
- Resume: on start, `checkpoint_store.is_completed(file_path)` filters the
  file list before dispatching to the pool — already-analyzed files (from a
  prior run OR already cached via `scan_index.py`, whichever check is
  cheaper) are never re-dispatched.
- Pause: the main process checks `checkpoint_store.is_paused()` between
  pool results; on a pause request, stop submitting new work, let in-flight
  workers finish (per the design discussion's explicit pause-semantics
  decision — never abort mid-write), flush, and return a `paused` status.

### 1.3 check_balances: re-point checkpoint, no concurrency change (`tools/check_wallet_balances.py`)

Per design-discussion §5b's confirmed verdict: concurrency design unchanged.
- `_flush_checkpoint()`'s full-dict `json.dump` is replaced with
  `checkpoint_store.mark_completed(f"{crypto_name}|{file_path}|{address}")`
  calls from inside `check_one()`, at the same call sites the existing
  `CHECKPOINT_EVERY_ADDRESSES`/`CHECKPOINT_EVERY_SECONDS` gate already fires.
  The `results` dict itself still needs to exist in memory for the final
  `output_file` write (parity with today), but is no longer what gets
  serialized on every periodic flush — only the completed-unit *set*
  changes, and that's the store's job now, not a full dict re-dump.
- `GLOBAL_MAX_WORKERS` and `PER_COIN_MAX_CONCURRENCY` become function
  parameters (still defaulting to today's tuned values, 64 and 15) sourced
  from the new resource-control settings (§1.6) instead of hardcoded module
  constants.
- Pause: same `is_paused()` check inside `check_one()`, at the existing
  lock-guarded checkpoint block — new work stops being submitted, in-flight
  requests finish.

### 1.4 Search walk parallelism (`tools/search_wallets.py`)

Today: single-threaded `os.walk`. New: a bounded thread pool of walkers
over a shared work queue, seeded with `start_path`.

```
queue = Queue(); queue.put(start_path)
def worker():
    while True:
        directory = queue.get()
        if checkpoint_store.is_completed(directory): continue
        entries = os.scandir(directory)  # one level, not recursive
        for entry in entries:
            if entry.is_dir(): queue.put(entry.path)
            else: check_against_patterns(entry)  # existing match logic, unchanged
        checkpoint_store.mark_completed(directory)
        queue.task_done()
```

Matches (`potential_wallets`) still append to `output_file` under a single
lock (small, uncontended critical section — writing one line is fast).
Worker count defaults conservatively low (2-4) given the confirmed real
interaction risk with rclone's own API pacing (design-discussion §5) —
**this must be load-tested against a real mounted Google Drive before
landing**, not shipped on faith. Excludes logic (`_is_excluded`) is
unchanged, applied per-directory exactly as today.

### 1.5 Job durability + real Pause (`web/jobs.py`, new `web/jobs_store.py`)

`web/jobs.py`'s `_jobs = {}` in-memory dict is replaced with a small sqlite
table (`web/jobs_store.py`, same WAL/busy-timeout discipline as §1.1):

```sql
CREATE TABLE jobs (
    job_id TEXT PRIMARY KEY, kind TEXT, label TEXT, status TEXT,
    started_at REAL, progress_json TEXT, result_json TEXT, error TEXT,
    secret INTEGER, checkpoint_path TEXT
);
```

`create_job`/`start_job`/`report_progress`/`get_job` keep their existing
call signatures (every current call site in `web/app.py` is unaffected) —
only the storage backend changes, from a dict to this table. `checkpoint_path`
is a new column: whichever stage function a job wraps records its own
checkpoint path here, so a new `POST /jobs/<job_id>/pause` route can look it
up, open that path's `CheckpointStore`, and call `request_pause()` without
the route needing to know which stage it's pausing.

New job `status` value: `"paused"` (alongside today's `running`/`done`/
`error`). A "Resume" action on a paused job is just: re-dispatch the exact
same stage function with the exact same `checkpoint_path`/`output_dir` —
already-completed units are skipped automatically, identical mechanism to
today's crash-resume, just user-triggered instead of only crash-triggered.

### 1.6 Resource-control settings (`web/scan_settings.py`, new + UI)

Confirmed with the user: default to **auto-detecting machine specs**, not a
user-picked named tier, with manual override still available.

```yaml
# stored via a small key-value settings table, same pattern as other
# small persisted app state (mirrors web/vault.py's simplicity, not a
# new heavyweight config system)
mode: auto   # auto | custom
overrides:    # only read when mode == custom
  search_walk_threads: null
  analyze_processes: null
  check_balances_global_workers: null
  check_balances_per_coin_concurrency: null
```

**Auto mode** computes worker counts from `os.cpu_count()` at call time —
stdlib-only, no new third-party dependency (this repo's dependency list is
currently just `requests` + `python-dotenv`; adding something like `psutil`
for memory-aware tuning is a real option but a separate decision, not
bundled into this epic without asking first). Illustrative formulas (tuned
during implementation, not frozen here):

| | Formula | Rationale |
|---|---|---|
| search_walk_threads | `min(4, max(1, cpu_count() // 2))` | I/O-bound; more than a handful of walkers adds no value and raises the rclone-quota risk (§ Risk R3) |
| analyze_processes | `max(1, cpu_count() - 1)` | CPU-bound; use most cores, leave one free for the Flask app itself |
| check_balances_global_workers | `64` (today's constant, unchanged) | Network-bound, not CPU/core-bound — cpu_count() isn't the relevant signal here |
| check_balances_per_coin_concurrency | `15` (today's constant, unchanged) | Same — already tuned against a real external API's rate limit, not local hardware |

UI: a settings-page section defaulting to "Auto" (showing the live computed
numbers for the current machine, read-only) with a "Custom" toggle that
reveals the same four fields as direct, editable numeric inputs — the
required advanced/manual path, now framed as "override auto-detection"
rather than a third named tier. Changing a setting takes effect on the
*next* job dispatch (each stage function reads its worker-count parameter
at call time, not from a live-reloaded global).

### 1.7 Concurrency-safety guard + mount health (`web/app.py`)

- Mirror `_running_find_job_for()` as `_running_check_balances_job_for(output_dir)`,
  called in every check-balances route before dispatch (same pattern, second
  call site, per design-discussion §4.4).
- Inside the search-walk loop (§1.4) and the check-balances loop (§1.3), add
  a periodic `is_mounted(remote_name)` call (every N directories/addresses,
  same cadence family as checkpoint flushes) when the job's target path is
  under a tracked mount point — on failure, flush current progress, mark the
  job `error` with a clear "drive disconnected" message instead of letting
  it silently stall or produce garbage partial results.

## Part 2: File Manifest

| File | Change |
|---|---|
| `tools/checkpoint_store.py` | **New.** Generic sqlite-backed checkpoint store (§1.1). |
| `tools/search_wallets.py` | Refactor inline checkpoint helpers to use `CheckpointStore`; add thread-pool walk (§1.4). |
| `tools/analyze_wallets.py` | Add `checkpoint_path` param, `multiprocessing.Pool`, resume support (§1.2). |
| `tools/check_wallet_balances.py` | Re-point checkpoint flush at `CheckpointStore`; make worker/semaphore counts parameters (§1.3). |
| `tools/crawl_transaction_graph.py` | Re-point checkpoint flush at `CheckpointStore` (lowest priority, format-consistency only — no live incident). |
| `run_pipeline.py` | Thread `checkpoint_path` into `analyze_wallets` call (currently only `search_for_wallets` gets it); pass resource-setting params through. |
| `web/jobs_store.py` | **New.** Sqlite-backed job registry (§1.5), same `create_job`/`start_job`/`report_progress`/`get_job` surface as today's `web/jobs.py`. Its db file (`web/jobs.db` in dev, `app_data_dir()/jobs.db` frozen) is **gitignored** — same pattern as every existing `*.db` in this repo (see `.gitignore` addition below). |
| `web/jobs.py` | Delegate to `jobs_store` instead of the in-memory dict; add `paused` status handling. |
| `web/scan_settings.py` | **New.** Resource-profile settings store (§1.6). Its db file (`web/scan_settings.db`) is likewise gitignored. |
| `.gitignore` | Add `/web/jobs.db` and `/web/scan_settings.db`, matching the existing `/web/findings.db`, `/web/crawl_runs.db`, etc. entries. |
| `web/templates/settings.html` | Add the resource-profile UI section (profile picker + advanced overrides). |
| `web/app.py` | New `POST /jobs/<job_id>/pause` route; `_running_check_balances_job_for()` guard; mount-health wiring into scan routes; settings read/write routes. |
| `web/mounts.py` | No functional change expected — `is_mounted()` is reused as-is, just called from a new site. |
| `tests/test_checkpoint_store.py` | **New.** Store contract: resume, run-key mismatch reset, pause signal, WAL/busy-timeout behavior under concurrent writers. |
| `tests/test_analyze_wallets.py` | Extend for resume + multiprocessing (mock `Pool` for deterministic tests, per existing test conventions in this repo). |
| `tests/test_check_wallet_balances.py` | Update checkpoint-format assertions to the new store; verify concurrency behavior unchanged. |
| `tests/test_jobs_store.py` | **New.** Durability across a simulated restart, pause/resume status transitions. |
| `tests/test_web_app_pause.py` | **New.** Pause route behavior, duplicate-check-balances-job guard. |
| `tests/test_scan_settings.py` | **New.** Profile defaults, custom overrides, persistence. |

## Part 3: Risk Registry

| # | Severity | Risk | Mitigation |
|---|---|---|---|
| R1 | High | Rewriting 4 pipeline stages' checkpoint I/O on a tool with 2 real incidents tonight risks a new, different bug | Land slice 1 (store + analyze) first and prove it thoroughly (new dedicated test file, real multi-thousand-file local test tree) before touching check_balances/crawl in later slices |
| R2 | High | `multiprocessing.Pool` in analyze: worker crash/exception handling, pickling edge cases (non-UTF8 paths, very large individual files) | Explicit exception capture per-worker-result (mirror `check_wallet_balances`'s existing `future.result()` re-raise pattern); a single bad file must not kill the whole pool |
| R3 | Medium | Search-walk thread pool concurrency directly interacts with the rclone quota incident from tonight (more concurrent Python-side reads → more concurrent rclone API calls underneath) | Conservative default (2-4 threads), explicit load test against the real Google Drive mount before this slice ships, independent tuning from rclone's own `--checkers`/`--tpslimit` |
| R4 | Medium | Shared sqlite store under real multi-process (not just multi-thread) writers — analyze's `Pool` workers are separate OS processes | WAL mode + busy_timeout from day one (§1.1); confirmed design keeps *all* sqlite writes in the main process (§1.2) for analyze specifically, sidestepping true multi-process write contention on the store itself for that stage |
| R5 | Medium | Pause semantics: a worker mid-request when pause fires | Confirmed decision: let in-flight units finish, never abort mid-write — applies uniformly across all four stages |
| R6 | Low | Job registry migration (`web/jobs.py` dict → sqlite) touches every existing job call site | Preserve the exact existing function signatures (`create_job`/`start_job`/`report_progress`/`get_job`) so no caller in `web/app.py` needs to change beyond the pause-specific additions |
| R7 | Low | This tool handles real private keys/wallet secrets, and the repo is public — new store files must never get committed, and must never contain wallet data | Verified directly: every existing `*.db` file in this repo is already gitignored (`web/findings.db`, `web/crawl_runs.db`, `web/scan_index.db`, `web/scan_history.db`, `web/auto_unlock_history.db`), `.env` is gitignored, and a repo-wide scan for tracked wallet/key/db-like files turned up nothing but source code and planning docs. The two new db files (`web/jobs.db`, `web/scan_settings.db`) get the same gitignore treatment from the first commit that creates them (§ file manifest), and — same as R7's original scope — new stores persist only progress metadata (paths, counts, status), never key material, matching every existing checkpoint/cache in this repo; an explicit test asserts this |
| R8 | Low | Resource-profile settings drift out of sync with the actual hardcoded defaults they're meant to replace | Settings module reads its "Balanced" profile defaults FROM the existing module constants (`GLOBAL_MAX_WORKERS`, etc.) at definition time, not a separately-maintained duplicate number |

## Part 4: Elicitation (planning team stress-test)

**Q1: Why extract a generic store instead of just fixing check_balances' checkpoint like search's was fixed tonight, one at a time?**
A: Three formats already exist for the same underlying problem (§ ground
truth in design-discussion). Fixing check_balances the same ad-hoc way
tonight's search fix was done would make it four, not fewer. The user's
explicit ask ("checkpoint, store") is for the unification itself, not just
more individual patches — and the store is a small, well-scoped module
(§1.1 is <100 lines of real logic), not a large abstraction-for-its-own-
-sake risk.

**Q2: Is `multiprocessing` actually justified for analyze, or is this
over-engineering for a personal tool?**
A: Justified by the workload shape, not by "processes sound faster."
Analyze is CPU-bound regex matching over file content — Python threads
provide zero real parallelism here (GIL). The alternative (leave analyze
sequential) means a real multi-core machine still processes a million-file
backlog one file at a time, directly contradicting the confirmed "if I get
more cores... let it use more resources" requirement. This is the one
stage in the whole pipeline where the tool is explicitly asking for it.

**Q3: What happens to a scan already in progress (mid-checkpoint, old
format) when this ships?**
A: Same precedent as tonight's search-checkpoint format change: an
in-progress checkpoint in the old format is abandoned, not migrated —
the stage starts that specific interrupted run over from scratch once,
under the new format, going forward. No migration shim, consistent with
this session's established "don't build backwards-compat hacks" guidance.
This should be called out plainly in the shipped changelog entry per slice.

**Q4: Does the Pause button need to work mid-network-request (e.g., stop
an in-flight balance-check API call immediately)?**
A: No — confirmed decision (design-discussion, risk R5) is "let in-flight
work finish." A paused check-balances job stops *starting new* requests;
whatever's already in flight (bounded by the per-coin semaphore, at most
~15 per coin) completes normally before the job reports `paused`. This
keeps the implementation simple and avoids ever leaving a checkpoint in a
half-written state.

**Q5: Is there a risk the resource-profile settings UI ships before the
underlying knobs it controls actually exist (a setting with nothing wired
to it)?**
A: Mitigated by slice ordering: slice 2 wires the *first* two settings
(check_balances' worker counts) end-to-end as a small, provable slice
before slice 6 generalizes the UI to all stages — the UI is never built
ahead of something real for it to control.

## Part 5: Decision points for user sign-off

1. Store module location: `tools/checkpoint_store.py` (reusable by both
   standalone tool scripts and the web app, matching how `tools/*.py`
   already work today) — confirm, or prefer a different location?
2. Job registry: new `web/jobs_store.py` file, or fold directly into the
   existing `web/jobs.py` (smaller diff, less clean separation)?
3. Confirm §1.6's illustrative Low/Balanced/Max default numbers are
   reasonable starting points (they're explicitly "tuned during
   implementation," not frozen) — or do you have specific numbers in mind
   for your own machine?
