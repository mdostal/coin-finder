# Vertical Plan: Scalable Scan Engine

Six slices, sequential (each depends on the prior slice's stories), each
leaving the product in a genuinely working state. Priority order matches
the user's confirmed decision: store + analyze resume first.

## Slice 1 — Shared store + analyze resume/parallelism (highest priority)

Extract the generic checkpoint-store module from `search_wallets.py`'s
already-working sqlite design (shipped tonight), then wire
`analyze_wallets.py` onto it with real per-file resume AND real
`multiprocessing.Pool` parallelism. Fixes the single biggest live
correctness gap: a crash mid-analyze today restarts that entire stage from
zero. Working state after this slice: search and analyze both survive a
crash/restart with zero lost progress, and analyze uses multiple cores for
the first time.

## Slice 2 — check_balances onto the shared store + first settings

Re-point `check_wallet_balances.py`'s checkpoint flush at the shared store
(fixes the full-dict-rewrite anti-pattern confirmed in design-discussion
§5b — the same shape of bug that caused tonight's OOM, just not yet
triggered). Concurrency design (ThreadPoolExecutor + per-coin semaphores)
stays as-is per the confirmed decision. Expose `GLOBAL_MAX_WORKERS` and
`PER_COIN_MAX_CONCURRENCY` as the first real settings (minimal UI — this
slice proves the settings plumbing end-to-end before slice 6 generalizes
it). Working state after this slice: every stage that talks to the network
is on the same safe checkpoint design, and the user can already adjust
balance-check concurrency without editing code.

## Slice 3 — Parallelize the search walk

Thread pool for the directory walk itself (§4.2a), built on slice 1's
store for claiming not-yet-completed subtrees safely across workers.
Conservative default worker count given the real rclone-quota interaction
risk flagged in design-discussion §5 (load-test against a real mounted
drive before landing). Working state: the walk stage uses real concurrent
directory reads, not just rclone's own background concurrency.

## Slice 4 — Job durability + real Pause

Migrate `web/jobs.py`'s in-memory job registry onto the shared store so a
job's existence/status survive an app restart (today's registry wipe is
why a dead backend loses the whole job, not just its progress). Add a
cooperative pause signal, checked at existing checkpoint-flush points in
every stage from slices 1-3, wired to a real "Pause" button in the UI —
confirmed as the required UX, not a "quit to resume" fallback. Working
state: a user can pause a running scan or balance-check from the UI and
resume it later from the exact same point, and a killed/crashed app no
longer loses an in-progress job's identity.

## Slice 5 — Concurrency-safety guard + mount health

Extend the existing `find`-only duplicate-job guard to `check-balances`
jobs (closes the last-writer-wins race confirmed in research). Wire the
existing `is_mounted()` health check into the running scan loop so a dead
mount fails the job with a clear reason instead of silently stalling.
Working state: two accidental concurrent balance-check jobs can no longer
corrupt each other's results, and a drive that disconnects mid-scan
produces an actionable failure instead of a silent hang.

## Slice 6 — Full resource-profile UI

Generalize slice 2's settings UI to every stage's concurrency knob (search
walk threads, analyze worker processes, plus the already-exposed
check_balances workers): a named profile picker (Low/Balanced/Max) setting
sensible per-stage defaults, plus an advanced section with direct
per-stage numeric overrides — both required per the confirmed decision.
Working state: the full resource-control story from the design discussion
is realized — safe defaults out of the box, real dials for better
hardware, without editing any code or config files.
