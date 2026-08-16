# Design Discussion: Scan File List + Selective Actions

**Process note:** same no-live-teammates adaptation as every epic this
session. Requested directly, and pointedly: "scan right now does not save
the found files and I WANT TO SEE the fucking files, with their names,
and be able to choose to do the full dive of 'check balance, get graph
etc' OR fire off just balance check OR whatever." Confirmed real: the
current Find results page (`scan.html`) only shows aggregate coin counts,
never the individual file paths that produced them.

## 1. What Are We Doing?

Two things, on the Find (Stage 1) results page:
1. **Show the actual file list** -- every file that matched, with its
   per-coin address counts, not just the aggregate total.
2. **Selective actions** -- checkboxes per file, with buttons to check
   balances for just the selected files (not the whole directory), or
   graph/fork-check their Bitcoin addresses directly -- instead of only
   the existing all-or-nothing "Check balances now" for the entire scan.

## 2. What I Found

- `tools/analyze_wallets.py`'s `analyze_wallets()` already writes the full
  per-file breakdown to `wallet_analysis.json`
  (`{file_path: {coin: [addresses]}}`) -- `run_pipeline.find()` already
  loads this exact dict (~line 51) just to sum it into aggregate
  `coin_counts`, then throws the per-file detail away before returning.
  The data already exists on disk; it's not persisted into the summary
  the UI renders. No new computation needed, just don't discard it.
- `tools/check_wallet_balances.py`'s `check_wallet_balances(input_file,
  output_file, ...)` takes a plain JSON path as `input_file` -- it has no
  concept of "the whole scan," it just reads whatever `{file_path: {coin:
  [addresses]}}` dict is at that path. A **filtered subset** of
  `wallet_analysis.json` (just the selected files) is a completely valid
  input -- no changes needed to this function itself.
- `run_pipeline.check_balances(output_dir, ...)` (the Stage 2 wrapper)
  always points at the ONE fixed `wallet_analysis.json` for that
  `output_dir` and writes to that same `output_dir`'s fixed output paths
  -- running it against a selection would either need a filtered
  temporary input file (easy) or risk overwriting the full scan's own
  `wallet_balances.json` if selective runs shared the same output paths
  (must avoid -- a selective run needs its own output location).
- `web/app.py`'s `_run_check_balances_job(output_dir, job_id)` (~line
  1110) is the reference for the whole-directory flow: runs
  `run_pipeline.check_balances()`, then loops the resulting
  `wallet_balances.json` calling `record_finding()` per address --
  exactly the same finding-recording step a selective run needs too.
- `web/templates/findings.html`'s bulk-select pattern (shipped this
  session, v0.33.0): a page-level hidden form + plain (un-wrapped)
  checkboxes referenced by `web/static/findings.js`, with `formaction`
  overriding which route a shared submit button posts to. Directly
  reusable here, one adaptation: findings.html's checkboxes each carry
  exactly one address as their value; a file here can carry *several*
  Bitcoin addresses, so the checkbox needs a `data-addresses` attribute
  (comma-joined) that the bulk-select JS reads instead of the checkbox's
  own `value` when the target is Graph/Check-fork-coins (the file's own
  path is still the `value` for the balance-check action, since that one
  filters by file, not by address).

## 3. My Proposed Approach

**`run_pipeline.find()`** gains a `"files"` key in its returned summary:
`[{"path": str, "coins": {coin: count}}, ...]`, sorted by total matched
address count descending (most address-dense file first -- the ones most
likely to be worth checking). Built from the exact same `analysis` dict
already loaded (~line 51) -- no new I/O, no new pipeline stage.

**`scan.html`** renders this as a real table (file path, per-coin counts,
a checkbox) instead of only the aggregate coin_counts table (which stays,
it's still useful as a quick skim). A bulk toolbar above it: "Check
balances for selected", "Graph selected" (Bitcoin files only), "Check
fork coins for selected" (Bitcoin files only) -- mirroring
`findings.html`'s exact toolbar shape. The existing whole-directory "Check
balances now" button stays too, for "just do everything."

**New route `POST /scan/<job_id>/check-balances-selected`**: takes a list
of selected file paths, writes a filtered `{file_path: {...}}` subset of
`wallet_analysis.json` to an isolated temp location, runs
`check_wallet_balances()` directly against it (not the `output_dir`-wide
`run_pipeline.check_balances()` wrapper, which would overwrite the full
scan's own results) into its own fresh output paths, records findings the
same way `_run_check_balances_job` does, and renders through the
**existing** `scan_balances.html` template -- same shape of results
(balances/inconclusive/filtered tables), just scoped to the selection.
Filter/relationship-graph stages are skipped for a selective run (they're
about correlating across the *whole* scan; a hand-picked subset doesn't
need them, and skipping keeps a "just check these two files" run fast).

**Graph/Check-fork-coins for selected**: no new backend route at all --
reuses the existing `/item/crawl` and `/item/fork-coins` routes exactly as
`findings.html`'s bulk toolbar already does, just sourcing the address
list from selected files' `data-addresses` instead of selected findings'
own addresses.

## 4. What This Does NOT Change

- The existing whole-directory "Check balances now" flow
  (`scan_check_balances`/`_run_check_balances_job`) -- untouched, still
  the "just do everything" path.
- `check_wallet_balances()`, `filter_wallet_balances()`,
  `build_relationship_graph()` -- reused unmodified.
- `/item/crawl` and `/item/fork-coins` -- reused unmodified, same as
  `findings.html`'s own bulk toolbar already does.

## 5. Risks

- **A file with a huge false-positive address count (OKCash/DigiByte/
  Ripple loose-match pattern, already called out on this page) could make
  the per-file table very long for a big drive.** Not solved here --
  sorting by address-count-descending at least puts the noisiest matches
  together rather than interleaved; a "hide files under N addresses"
  filter is a reasonable follow-up if it turns out to matter in practice,
  not blocking this epic.

## 6. Scale Assessment

**Small-to-medium.** One field added to an existing summary dict (no new
I/O), one new route (reuses existing lower-level functions), one new bulk
toolbar (direct pattern reuse from `findings.html`/`findings.js`). Two
stories: (1) expose + render the file list, (2) the selective actions.
