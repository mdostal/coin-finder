# Design Discussion: Scalable Scan Engine

## 0. Prelude

- Base branch: `dev` (this project's own established convention — confirmed
  via real branch history and repeated explicit user instruction — not
  `develop`/`main`; the generic git_flow helper isn't vendored in this repo,
  so this was resolved manually against real project practice instead of a
  textbook default).
- No prior KG decisions or north-star audit-trail tooling wired into this
  repo (`hive/lib/kg_why` etc. are part of the plugin-hive tooling, not
  this project) — proceeding on direct codebase research instead.
- `.pHive/project-profile.yaml`'s own north star already names the
  relevant pain point: *"no automated tests... changes risk silently
  breaking a wallet service"* and *"be as accurate and thorough as
  possible when crawling multi-terabyte drives."* This epic is squarely
  in that lane.
- Research was done directly against the live codebase tonight (a
  dedicated research pass, not reused guesswork) — see §2 for exact
  findings with file:line references.

## 1. Why now

Two real incidents tonight, both on the same code path (`tools/search_wallets.py`
walking a mounted multi-terabyte Google Drive):

1. **OOM crash.** The scan's checkpoint held every completed directory as a
   full path string in an in-memory Python `set`, and rewrote the *entire*
   sorted set to JSON on every flush. Confirmed live: 34,199 directories in,
   already a 3.85MB file rewritten every ~20s, unbounded for the life of the
   scan. Fixed earlier tonight (v0.53.6) by moving to a sqlite-backed index.
2. **rclone quota throttling.** `--checkers 32` (added to fix a separate
   slowness complaint) burst past Google Drive's shared default-client API
   quota. Fixed tonight (v0.53.5) by dropping to `--checkers 16` + `--tpslimit 8`.

Both were real, necessary, narrowly-scoped patches — but they only fixed the
*search* stage, and only the specific failure modes that happened to surface
tonight. The user's ask now is broader: don't keep finding these one at a
time — make the whole pipeline structurally sound for terabyte-scale,
resumable, pausable operation.

## 2. Ground truth: what exists today (research findings)

| Stage | Concurrency | Checkpoint / resume | Format |
|---|---|---|---|
| **search** (`search_wallets.py`) | Sequential `os.walk` | Yes (fixed tonight) | sqlite, per-directory |
| **analyze** (`analyze_wallets.py`) | Sequential, one file at a time | **None at all** — only an *incidental* skip via optional content-hash cache (`index_db_path` → `scan_index.py`), and that cache is opt-in, not always wired | sqlite (cache, not a checkpoint) |
| **check_balances** (`check_wallet_balances.py`) | Real `ThreadPoolExecutor`, `GLOBAL_MAX_WORKERS=64`, per-coin `Semaphore(15)` | Yes, already solid | JSON, full-dict rewrite per flush |
| **crawl** (`crawl_transaction_graph.py`) | Sequential | Yes (two-phase: per-generation + per-address) | JSON, full-dict rewrite per flush |
| **job registry** (`web/jobs.py`) | One `daemon` thread per job | **None** — plain in-memory dict, wiped on every app restart (this is why tonight's dead backend lost the running job entirely) | in-memory only |

Other confirmed gaps, not yet visible as incidents but real:

- **No guard against two concurrent `check-balances` jobs on the same
  `output_dir`.** Unlike `find` (which has an explicit duplicate-job guard
  added after a real incident), two balance-check jobs racing would
  last-writer-wins clobber the same checkpoint and output JSON — no lock
  between separate Python-level calls.
- **No WAL mode / busy-timeout on any `sqlite3.connect()` in the repo** —
  fine for today's single-writer-at-a-time pattern, but a real risk the
  moment more than one process/thread writes to the same db concurrently.
- **No mount health check during a long scan.** `is_mounted()` exists and
  is used at page-load and in the mounts UI, but nothing re-checks it once
  a scan is walking a mount — a dead mount surfaces only indirectly, through
  whatever I/O errors bubble up.
- **Three different checkpoint formats** (sqlite for search, JSON for
  check_balances, JSON for crawl) that each reinvented the same problem —
  "durably remember what's done so a restart doesn't repeat it" — with
  different schemas, different flush cadences, no shared code.
- **Analyze has no per-file streaming** — reads each whole file into memory
  before regex-matching it; bounded today only by `search_wallets.py`'s
  `MAX_FILE_SIZE` filter upstream, not by anything in `analyze_wallets.py`
  itself.

## 3. Reframing "infinitely scalable" (needs your sign-off — see §6.1)

Taken literally, "infinitely scalable across all the processes" reads like
a distributed-systems ask. This is a single-user local desktop app (per the
project's own north star: *"single-user local CLI tool; no concurrency or
hosting concerns"*) — a real distributed architecture (multiple machines,
a job queue, workers) would be significant overbuild for that.

What I think you actually need, and what this plan targets, is:

- **Flat resource use regardless of drive size** — memory and per-checkpoint
  cost stay constant whether the drive has 10,000 or 10,000,000 files (the
  search stage already has this now; analyze and the job registry don't).
- **Real multi-threading/multi-processing on this one machine**, using all
  available cores/bandwidth instead of one sequential pass — genuine
  speedup, not just "doesn't crash."
- **Resume across a crash/quit** (already true for search and
  check_balances) **and analyze** (the one stage with zero coverage today).
- **A real pause you can trigger from the UI**, not just "quit the app and
  hope the checkpoint picks back up" — distinct capabilities, and today
  only the second one exists.

## 4. Proposed approach

**4.1 — One shared checkpoint/store abstraction.** Replace the three
bespoke formats with a single reusable sqlite-backed store (schema: a
generic `completed_units` table keyed by unit-of-work id, a `metadata` table
for run-identity, WAL mode + a real busy-timeout from day one). Every stage
— search, analyze, check_balances, crawl — uses the same module. This is
the direct fix for "checkpoint, store" and removes the format-proliferation
problem at the root instead of patching each stage separately.

**4.2a — Parallelize the search (walk) stage too.** Today's `os.walk` is
fully sequential — one directory at a time, even though directory listing
is I/O-bound (exactly the kind of work Python threads DO help with, since
I/O releases the GIL). A thread pool of walkers, each claiming a
not-yet-completed subtree from the shared store (§4.1) and recursing into
it, turns "multi-reading" from an rclone-side-only property (today's
`--checkers 16`) into something the app itself does too — real concurrent
directory reads, not just concurrent network requests underneath a
single-threaded walker. Worker count should be tunable and conservative by
default (mounted network drives have their own throttling concerns, per
tonight's rclone quota incident) — this parallelizes the Python-side walk,
it does not replace or bypass rclone's own pacing.

**4.2b — Give analyze real resume + real parallelism.** This is the single
biggest live gap. Analyze is CPU-bound (regex matching over file content) —
Python threads don't help here (GIL), so this is the one stage where
`multiprocessing.Pool` is actually justified by the workload shape, not just
"parallel because it sounds faster." Each worker process claims a file,
analyzes it, and records completion against the shared store from §4.1 —
a crash mid-analyze resumes from exactly where it left off, and multiple
cores are actually used for the first time in this stage.

**4.3 — Job-level durability + real pause.** Move `web/jobs.py`'s registry
from an in-memory dict to the same sqlite store, so a job's existence and
status survive an app restart (today's job registry wipe is why tonight's
dead backend lost the running scan entirely, not just its progress). Add a
cooperative pause signal (checked between checkpoint flushes, same points
that already exist) so pause is a real, intentional user action from the
UI — "stop now, resume exactly here later" — distinct from crash-recovery.

**4.4 — Close the concurrency-safety gap.** Add the same duplicate-job guard
`find` already has to `check-balances`, and let the shared store's own
write serialization (real locking, not per-call in-process locks that don't
know about each other) remove the last-writer-wins race outright.

**4.5 — Mount health during a scan.** Periodically re-check `is_mounted()`
while a scan is walking a mount (the check already exists — this is wiring
it into the long-running loop, not building it from scratch) so a dead
mount fails the job with a clear reason instead of silently stalling.

**4.6 — User-facing resource controls.** Confirmed with the user: "scalable"
means handling a petabyte-scale drive by working through it in sections
over time without killing the machine, on whatever hardware is available
today — and being able to turn the dial up on better hardware later. This
is a real, first-class requirement, not an implementation detail:

- Every tunable introduced above (walker thread count §4.2a, analyze worker
  process count §4.2b, check_balances thread-pool size — already
  configurable in code today, just not exposed) becomes a real setting in
  the UI (`web/templates/settings.html` + a small settings-store module,
  following the existing settings patterns already in this app), not a
  hardcoded constant.
- Ship with **conservative, safe-by-default** values (today's constants —
  e.g. `GLOBAL_MAX_WORKERS = 64` for balances, single-threaded walk/analyze
  — are reasonable floors) so a fresh install never surprises anyone with
  high resource use.
- A simple resource-profile control (e.g. "Low / Balanced / Max" or a raw
  worker-count slider — exact UX is a planning-phase decision, not decided
  here) lets the user trade speed for machine impact explicitly, and
  changing it takes effect on the *next* job, not by editing config files.
- This directly motivates keeping every new concurrency knob **runtime-
  configurable and independent per stage** (walk vs. analyze vs. balance-
  check each get their own setting) rather than one global "concurrency"
  number — the stages have different bottlenecks (I/O vs. CPU vs.
  network-API-rate-limited) and a single shared knob would under-serve at
  least one of them.

**What this does NOT propose:** distributed/multi-machine execution, a
message queue, or a service split. Everything above runs as threads/
processes within the existing single Flask app process, on one machine —
consistent with §3's reframing.

## 5. Risks

| Risk | Mitigation |
|---|---|
| Rewriting core pipeline stages on a tool that just had 2 real production incidents tonight | Land the store (§4.1) and analyze fix (§4.2b) first as the highest-value, most bounded change; keep check_balances's already-solid thread-pool design largely as-is (re-point its checkpoint writes at the shared store, don't redesign its concurrency) |
| Parallelizing the walk (§4.2a) directly interacts with tonight's other real incident — more concurrent Python-side directory reads against a Google Drive mount means more concurrent rclone API calls underneath, which is exactly what tripped the shared-client quota with `--checkers 32` | Keep walker concurrency low and configurable by default, and treat it as fully independent from rclone's own `--checkers`/`--tpslimit` tuning — this is not a reason to skip §4.2a, but it must be load-tested against a real mounted drive before landing, not assumed safe |
| `multiprocessing` adds real complexity (worker pool lifecycle, pickling paths across processes, harder debugging) | Scope it to the one stage where it's actually justified (analyze, CPU-bound); do not reach for it in search/check_balances, which are I/O-bound and already served by threads |
| Shared sqlite store under real multi-process write contention | WAL mode + explicit busy-timeout from the first line of the new module, not retrofitted later |
| Pause semantics for in-flight work (a worker mid-request when pause fires) | Decide explicitly in planning: let in-flight units finish, don't abort mid-write — never leave a checkpoint in a half-written state |
| This tool handles real private keys/wallet secrets (per `hive.config.yaml`'s own developer note) | The new store persists only progress metadata (paths, counts, status) — never key material; same discipline already followed by every existing checkpoint/cache in this repo |

## 5b. check_balances investigation (requested, not assumed)

Read `tools/check_wallet_balances.py` directly rather than deciding blind.
Finding: **its checkpoint flush has the exact same anti-pattern that
caused tonight's OOM crash** — `_flush_checkpoint()` (line 178-183) does
`json.dump({"input_file": ..., "results": results}, f)`, a full rewrite of
the *entire* `results` dict (every address checked so far, for the whole
run) on every flush (every 20 addresses or 15 seconds), with `results`
held fully in memory for the process lifetime. It hasn't caused a visible
incident yet only because a single scan's address count has stayed smaller
than a multi-terabyte drive's directory count — but real numbers from
tonight (3,825 addresses in one wallet alone, ~14,990 findings total in
the live db) show this is not a hypothetical scale concern once the
analyze-stage fix (§4.2b) starts surfacing larger backlogs of
never-checked addresses.

**Verdict:** the *concurrency* design is genuinely solid and should NOT be
redesigned — `ThreadPoolExecutor` + per-coin `Semaphore(15)` +
`GLOBAL_MAX_WORKERS=64` is well-reasoned and already tuned against a real
live benchmark (documented in its own comments: 15 concurrent per coin
more than doubled throughput over 5 with zero increase in errors). What
needs to change is exactly what §4.1 already proposes for every stage:
move its checkpoint writes onto the shared store (incremental per-address
persistence, not a full-dict rewrite every flush) and expose its existing
`GLOBAL_MAX_WORKERS`/`PER_COIN_MAX_CONCURRENCY` constants as the §4.6
resource-control settings instead of hardcoded values. This resolves
open question 3 below with evidence rather than a guess.

## 6. Decisions (resolved with the user)

All open questions from the draft are now resolved:

1. **Scope reframing (§3)** — confirmed. "Flat resource use regardless of
   drive size + real multi-core use on this one machine, working through a
   petabyte-scale drive in sections over time without killing the machine"
   is exactly what was meant. Not distributed/multi-machine.
2. **Resource controls (§4.6)** — confirmed as a first-class requirement,
   not an implementation footnote: "if I get more cores, a faster machine,
   I should have toggles and settings and controls to let it either use
   more resources, or run slowly at a diminished resource use."
3. **Priority order** — **store + analyze resume first.** The shared
   checkpoint store (§4.1) and analyze's resume/parallelism fix (§4.2b) —
   the biggest live correctness gap — ship as the first slice. Job-level
   pause/resume (§4.3) and the concurrency-safety guard (§4.4) follow.
4. **Pause UX** — **a real Pause button.** An intentional UI action that
   stops a running job on demand and resumes it later from the exact same
   point — not just relying on quit-and-relaunch.
5. **check_balances** — investigated directly (§5b), not assumed: **leave
   the concurrency design as-is** (it's genuinely well-tuned), but its
   checkpoint flush has the *identical* full-dict-rewrite anti-pattern that
   caused tonight's OOM crash and must move onto the shared store like
   every other stage. Its existing worker/semaphore constants become
   user-facing settings per §4.6, not a redesign of the design itself.
6. **Resource-profile UX (§4.6)** — **both**, confirmed explicitly: a named
   profile (Low/Balanced/Max) that sets sensible per-stage defaults, PLUS
   an advanced section exposing the raw per-stage numeric worker-count
   controls directly — the advanced section is required, not optional or
   deferred.

## 7. Scale assessment

**Large.** This touches `search_wallets.py`, `analyze_wallets.py`,
`check_wallet_balances.py`, `run_pipeline.py`, `web/jobs.py`, `web/app.py`
(job dispatch + concurrency guards), `web/mounts.py` (health checks), plus
a new shared checkpoint-store module — multi-file, multi-layer, real
architectural risk on a tool already carrying real financial stakes.
Recommending full horizontal/vertical planning and a structured outline
with elicitation before story decomposition.
