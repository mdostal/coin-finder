# Design Discussion: web-ui-wizard-and-mounting

## Goal

Make the local web UI approachable enough that "any idiot can do this" (the
user's own bar), and unblock the two upcoming multi-terabyte crawls (Google
Drive, then the Arch Linux box with the physical old drives) that the rest
of this project's tooling has been building toward all session. Concretely:
a persistent, honest connectivity indicator; a guided setup wizard for
attaching a scan target; a reusable list of bound targets with one-click
full-drive scanning; and rclone-based mounting so a multi-TB Drive never
needs a full local download. Plus another visual pass -- direct live
feedback after v1 ("looking better, but still need another pass").

## Approach

Four vertical slices, each independently shippable, in dependency order:

**1. Connectivity status + job progress transparency.** A small
`/api/status` JSON endpoint (network status via the existing
`check_network_status()`, reused not reimplemented) polled by a persistent
header widget on every page (extends `base.html`'s nav, not a new page).
`web/jobs.py`'s job dict gains an optional `progress` field
(`{current, total, message}`) that long-running tools can update via a
callback; `check_wallet_balances.py`'s and `scan_wallet_dat.py`'s per-address
loops are the first to report through it (both already loop one-at-a-time --
adding a progress callback is additive, not a restructure). The scan/unlock
status pages render a real progress bar when present, falling back to the
existing indeterminate "working" state when a tool doesn't report progress.

**2. Bound targets + volume detection.** `web/bound_targets.py`: a tiny
JSON-file-backed store (add/list/remove), plus `list_mounted_volumes()`
(macOS: enumerate `/Volumes/*`, filtering the boot volume). A "Targets" page
lists bound targets and detected-but-unbound volumes side by side, each with
a one-click "Scan" button that posts straight to the existing `/scan` route
-- no new scanning logic, just a faster path to the form that already
exists.

**3. rclone mount tooling.** `scripts/install_rclone.sh` (brew install
rclone + macfuse cask, with the macFUSE manual-approval step called out
loudly, not silently assumed). `web/mounts.py`: wraps `rclone mount` as a
long-running background process (not a `web/jobs.py` job -- a mount is a
persistent daemon, not a one-shot task with a result) with `mount()`,
`unmount()`, `is_mounted()`, tracked in a small local state file. A
"Mounts" page lists configured remotes (from `rclone listremotes`) and
active mounts, mount/unmount buttons, and on a successful mount, one-click
"add to bound targets" (wires directly into story 2's store).

**4. Setup wizard + continued visual polish.** `/wizard`: a linear,
step-by-step flow (plain language at every step) that branches by target
type -- local directory (thinnest path: just the existing form), physical
drive (list detected volumes from story 2), Google Drive or GCS (walks
through story 3's install -> `rclone config` guidance -> mount -> bind, one
screen per step, each explaining *why* before *how*). This is the
"integration" slice -- it doesn't add new scanning/mounting mechanics, it
sequences stories 2 and 3 into one guided path for a non-technical user.
Alongside it: another visual-design pass per direct feedback (deeper
component polish, empty states, clearer hierarchy on the growing nav).

## Risks

- **macFUSE approval cannot be automated.** Real risk: the wizard silently
  implying "done" when the OS hasn't actually granted the extension yet.
  Mitigation: after triggering the install, the wizard polls
  `is_mounted()`-equivalent health check with a clear "waiting on macOS
  approval -- check System Settings > Privacy & Security" message rather
  than a spinner that could hang indefinitely with no explanation.
- **A stalled/crashed rclone mount could make a bound target look like an
  empty local directory** (a common FUSE failure mode -- unmounted-but-not-
  cleaned-up mountpoints read as empty, not as an error). Mitigation:
  `is_mounted()` checks rclone's own process/health, not just "does the
  path exist" -- surfaced on the Mounts page before a scan is ever started
  against it, so a scan doesn't silently report "found nothing" against a
  dead mount.
- **Progress reporting adds a callback parameter to existing tool
  functions** (`check_wallet_balances.py`, `scan_wallet_dat.py`) --
  a real signature change, not additive-only. Mitigation: default the
  callback to a no-op so every existing CLI/test call site is unaffected;
  only the web job wrapper passes a real one.
- **Scope.** This is the largest single epic this session besides
  `local-web-ui` itself. Mitigation: four vertical slices, each shippable
  and individually useful even if the epic stops after any one of them --
  same discipline as `local-web-ui`.

## Dependencies

- `rclone` (Homebrew, verified installable). `macfuse` cask (Homebrew,
  requires manual OS approval -- documented, not scripted around).
- No new Python package dependencies.

## Open questions

- Electron packaging: still explicitly out of scope, the user's own
  separate task (established at `local-web-ui`'s kickoff and reaffirmed
  this session).
- GCS bucket auth specifics (service-account key vs. user OAuth) are
  surfaced via `rclone config`'s own interactive prompts -- this epic
  doesn't re-implement GCS auth, only guides the user through rclone's.

## Verification strategy

- `web/jobs.py`'s progress field and `web/bound_targets.py`/`web/mounts.py`:
  unit tests, same TDD discipline as every prior story this session.
- `rclone`/macFUSE interaction: cannot be meaningfully unit-tested (real OS
  security approval, real cloud auth) -- covered by mocking
  `subprocess`/`is_mounted()` in tests, with a manual smoke-test note in the
  story itself (consistent with how `unlock_exodus_wallet.py`'s hashcat
  interaction was handled earlier this session: tested against known-safe
  fixtures, not live cloud accounts).
- Wizard: route-level tests (each step renders, branches correctly) --
  the multi-terabyte Drive scan itself is explicitly out of scope for
  automated testing (the whole point is it's the user's own real account).

## Scale assessment

**Large.** New cross-cutting infrastructure (progress reporting touches
existing tool signatures), a new persistent-process concept (mounts, unlike
every prior job which was one-shot), and a new guided-flow page type
(wizard) on top of the existing local-web-ui foundation. Per this session's
established solo/no-live-teammates adaptation, H/V planning is resolved
directly here as the four numbered vertical slices above, in dependency
order: connectivity/progress (foundation for the others' progress display)
-> bound targets (needed before mounts can "bind") -> mount tooling ->
wizard (sequences the other three for a guided experience). Each slice
ships independently, same discipline as `local-web-ui`.
