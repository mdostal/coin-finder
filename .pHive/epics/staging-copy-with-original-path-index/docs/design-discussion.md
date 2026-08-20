# Design Discussion: Staging Copy with Original-Path Index

## 0. Prelude

Base branch `dev`. Dedicated research pass against the live codebase, not
reused guesswork.

## 1. Why now

User's own words: *"we also should maintain a local copy so we can easily
handle them and do this when we do these scans and start figuring it out
with our findings, archive, etc -- and maintain the original pathing and
index so we can make decisions on what to do with the originals as well
when do this work."* Raised directly out of tonight's real source-path
investigation, where several findings turned out untraceable — partly
because real files live on ephemeral sources (a GDrive mount, an old
external drive) that may not always be reachable later.

## 2. Ground truth: what exists today

- **`/item/stage` already exists but is fully manual and has zero
  index.** A free-text form on the scan page lets the user type any file
  path and stage it — flat `shutil.copy2` into `DEFAULT_STAGING_DIR`,
  refuses to overwrite a same-named file, records **nothing** linking the
  copy back to its source. Not wired to findings/scans at all.
- **Only 3 of 6 `record_finding()` call sites ever have a real local file
  path.** `scan_wallet_dat`, and the two `check_balances` jobs (bulk +
  selected) pass a real `source_path`. `crawl_transaction_graph`,
  `check_fork_coins`, and `quick_lookup` are pure address/API-based
  discovery with no original file — by design, not a gap. This directly
  answers the open "what triggers auto-staging" question: **stage
  whenever `record_finding()` is called with a real, existing
  `source_path`** — the signal already exists, no new removable-vs-local
  detection heuristic needed for v1.
- **`source_path` is documented as "sometimes absent," never "sometimes
  wrong."** The app already treats a missing/moved source file as a
  normal, expected, handled state (`source_exists_by_path`, "missing/
  moved" badge) — auto-staging doesn't need to solve a data-integrity
  problem, just an availability one.
- **Today's collision handling (refuse-on-same-basename) is a real gap**
  worth fixing, not preserving: two different real files from different
  sources sharing a basename (e.g. two drives each with `wallet.dat`)
  can't both be staged today.
- **Real growth is currently trivial** (1 real staged-worthy file on this
  machine, ~0.92MB) but the backlog's own concern is prospective — a
  large drive scan could produce many wallet-shaped findings, each up to
  the existing ~1MB-class real file already observed tonight (1016
  addresses in one file).
- **Established schema convention to follow**: a dedicated `*.db` sqlite
  file per module (`_SCHEMA`/`_MIGRATIONS`/`_connect` boilerplate,
  `db_path=DEFAULT_DB_PATH` parameter for testability) — same shape as
  every sibling module (`findings.py`, `crawl_runs.py`,
  `credential_scan_cache.py`).
- **Established UI convention**: plain instant per-row POST for
  reversible/informational actions; a dedicated confirm-page (like Try-
  unlock/Extract-keys) reserved for actions with real destructive/safety
  stakes.

## 3. Proposed approach

**3.1 — Auto-stage on the existing `source_path` signal, not a new
heuristic.** When `record_finding()` is called with a real, existing
`source_path` (3 of 6 call sites), automatically copy the file into
staging and index it — no manual button needed for the common case (the
existing manual `/item/stage` form stays, for anything outside that
automatic path).

**3.2 — Content-hash-based staged filenames, fixing today's collision
gap.** `staged_path = staging_dir / f"{sha256-prefix}-{original_name}"` —
same naming discipline already established twice tonight (checkpoint
units, password-scan vault entries). Two different files sharing a
basename now both stage cleanly; the same file staged twice (re-scanned)
produces the same staged path, naturally deduplicating instead of
erroring.

**3.3 — New `web/staging_index.py`, following the established sibling-
module shape.** Own db file, table keyed by `staged_path`, columns:
`original_source_path`, `coin`, `address`, `source_label`, `staged_at`,
`decision` (`undecided` | `keep` | `archived` | `re-verify-pending`,
default `undecided`). No secret/key material — the same discipline as
every existing cache/history module.

**3.4 — Decision UI, scoped conservatively for v1.** A "Staged Files"
view lists each entry with its decision state. "Keep" and "Re-verify"
(check whether the original still exists/is reachable) are plain instant
POSTs — reversible, informational, matching this app's established
convention. **"Archive & forget" in v1 only marks the index decision — it
never touches/deletes the real original file.** Actually deleting a
user's real source file is a genuinely destructive action against data
outside this app's own storage; that's explicitly out of scope for this
epic, not silently built in. If real file-deletion is wanted later, it
deserves its own deliberate design pass (and the confirm-page pattern
already established for destructive actions), not a late-addition inside
this one.

## 4. Risks

| Risk | Mitigation |
|---|---|
| Auto-staging every wallet-shaped finding could grow storage unboundedly on a large drive scan | v1 relies on the existing upstream size filtering (search already bounds candidate file size); log a visible warning once total staged size crosses a soft threshold (e.g. 1GB) rather than silently growing forever -- a hard cap is a future refinement, not blocking v1 |
| "Archive & forget" implying real file deletion would be a genuinely destructive, hard-to-reverse action against the user's own data | Explicit scope decision (§3.4): v1 never deletes the original, only records the decision -- real deletion deserves its own separate, deliberate design pass |
| Today's flat/collision-prone staging behavior silently breaks for two same-named files from different sources | Fixed directly via content-hash naming (§3.2), not preserved |

## 5. Scale assessment

**Medium.** New `web/staging_index.py` module (established pattern, low
risk), a small hook into the 3 relevant `record_finding()` call sites,
and a new "Staged Files" review page. No new external dependency, no
destructive file operations. Proceeding to a lightweight vertical plan.
