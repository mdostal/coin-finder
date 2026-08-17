# Design Discussion: Auto-Unlock Overhaul

**Process note:** same no-live-teammates adaptation as every epic this
session. Direct, angry, and correct: "WHERE THE FUCK is the unlock
attempt for the entirety of the found wallets and matching them and
displaying cleanly in columns on what passcodes when to which wallets."
Confirmed live -- the feature exists (shipped mid-session as
`auto-unlock`) but has never actually been run in this session, and even
when run, has two real, user-visible gaps.

## 1. What Are We Doing?

Two confirmed gaps in the existing `/auto-unlock` feature:

1. **Results vanish forever.** `auto_unlock_result.html`'s own banner
   says it outright: "shown to you exactly once... never written to disk
   or logged. Leave that page and it is gone for good." Combined with
   `web/jobs.py`'s in-memory-only job registry (wiped on every restart --
   the same root cause `durable-scan-history` fixed for Find results,
   never extended here), a real run's outcome is lost twice over: once if
   you navigate away, again on every app restart.
2. **Even a successful run doesn't show the actual password.** Only
   which *vault entry label* matched ("Matches saved vault entry
   'password-3'") -- not the value itself. Forces a second lookup that
   `web/templates/vault.html` doesn't even support today (confirmed: zero
   "reveal value" action exists anywhere in the vault UI).

## 2. What I Found

- `_run_auto_unlock_job` (`web/app.py:1169`) already resolves every
  vault entry to its real value (`resolve_vault_entries_with_values`) and
  already knows, via `_match_vault_label`, which one matched -- the value
  is already in memory at the exact point the result is built, just
  discarded before it reaches the template.
- The "shown once, never persisted" design is real and deliberate (the
  page's own banner says so), but comparing against the single-wallet
  `/item/unlock` flow shows it's **inconsistent, not a stricter
  invariant**: `unlock_result.html` already shows the FULL raw btcrecover
  stdout for a single wallet -- which, on a real match, already contains
  the actual found password in plain, unstructured text. Auto-unlock's
  batch version is actually MORE conservative than the single-wallet
  flow it's built on top of, not equally so.
- `_known_wallet_paths()` (`:1160`) pulls from `list_findings()`'s
  `source_path` -- confirmed the real 0.3 BTC wallet.dat file (recorded
  earlier this session) is still on disk and would be included in a real
  run today.
- `web/vault.py`'s `resolve_vault_entries_with_values` already exists and
  is exactly the primitive a new "reveal this entry's value once" action
  needs -- no new resolution logic required, just a new UI entry point.

## 3. My Proposed Approach

**Story auo-01 -- show the real matched password, in a clean table:**
`_run_auto_unlock_job` returns `{wallet_path: {"vault_label": ..., "value":
...}}` instead of a bare label string -- `value` is the actual resolved
password when matched, `None` otherwise (mirrors what
`unlock_result.html` already exposes via raw stdout, just structured).
`auto_unlock_result.html` becomes a real table: Wallet | Matched password
| (source label as context) -- replacing the current two-column
label-only version. The once-only "shown once, gone forever" framing for
the RAW VALUE stays (matches the existing single-wallet precedent) --
what changes is that the value is actually visible in that one showing,
not withheld even then.

**Story auo-02 -- durable run history (metadata only, never raw values)
+ a real way to re-fetch a value later:** New `web/auto_unlock_history.py`
(sqlite, same `_connect`/`_SCHEMA` pattern as every other durable module
this session) recording `{run_id, wallet_path, vault_label, matched,
run_at}` per wallet per run -- explicitly NO password value column, ever.
`_run_auto_unlock_job` writes this after each wallet attempt. New
`GET /auto-unlock/history` page: every past run, which wallet, which
label matched (or didn't), when -- survives restarts, answers "did I
already try this" and "which saved password worked on which wallet"
durably, without ever persisting the secret itself.

Because the durable history only ever stores a *label*, not a value, a
real way to get back to the actual password later is needed --
`web/vault.py` already has the exact resolution primitive
(`resolve_vault_entries_with_values`), just no UI entry point. New
"Reveal" action on `vault.html`: resolves one named entry, shows its
value once (same once-only precedent as everywhere else in this app),
never written to disk. This is what makes the durable label-only history
actually useful days later, not just a historical curiosity.

## 4. What This Does NOT Change

- `run_unlock`/`run_exodus_unlock`/the actual unlock attempt logic --
  untouched.
- The offline-gate warning, network-status check, "run online anyway"
  override -- untouched, same behavior.
- `resolve_vault_entries_with_values`/the vault's own storage -- reused
  exactly as-is; no new place a raw password value gets written to disk.
- Single-wallet `/item/unlock` -- untouched (already shows the real value
  via raw stdout, the precedent this epic makes auto-unlock consistent
  with, not a change target itself).

## 5. Risks

- **This is the second-highest-stakes correctness surface in the app**
  (after confidence scoring) -- real passwords are involved. Mitigated by
  keeping the actual-value display exactly as ephemeral as the existing,
  already-shipped single-wallet flow (once-only, never persisted) --
  this epic makes auto-unlock consistent with an existing precedent, not
  a new, less-conservative one.
- **The durable history table is a new place secret-*adjacent* metadata
  lives** (which wallet, which label, whether it matched) -- explicitly
  scoped to exclude the raw value at the schema level (no column exists
  for it), not just an application-level promise.
- **The new "Reveal" vault action** is a new way to expose a raw secret
  value in the UI -- scoped identically to every other once-only reveal
  already in this app (item_unlock_result, auto_unlock_result), not a
  novel exposure pattern.

## 6. Scale Assessment

**Medium.** Two stories: result-display fix (auo-01, small -- the value
is already computed, just needs to reach the template), then durable
history + vault reveal (auo-02, medium -- one new sqlite module, one new
route+page, one new vault action).
