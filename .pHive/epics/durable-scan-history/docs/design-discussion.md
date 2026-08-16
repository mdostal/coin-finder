# Design Discussion: Durable Scan History

**Process note:** same no-live-teammates adaptation as every epic this
session. Requested directly: "once a scan finds wallets, this is supposed
to be saved, but clicking away just clears all results consistently."
Confirmed real via direct code inspection, not assumed.

## 1. What Are We Doing?

A Find (Stage 1) scan's rich results -- the file list, per-coin address
counts, hidden-volume report -- currently exist ONLY in
`web/jobs.py`'s in-memory `_jobs = {}` dict. That dict has zero disk
persistence. `/jobs`' own empty-state literally says "No jobs yet **this
session**." Any app restart (a normal `Cmd+Q` + relaunch, or -- sobering
realization while investigating this -- every version-bump reinstall this
session did exactly that) wipes every scan's results that hadn't already
been through Check Balances (which alone writes durably, via
`record_finding()` into `findings.db`).

This adds a durable, restart-proof way to always get back to what a scan
found.

## 2. What I Found

- `run_pipeline.find()` already writes `wallet_analysis.json` to a real,
  durable directory on disk (`output_dir/checks/`) -- the underlying DATA
  already survives a restart. What's missing is (a) the *computed summary*
  built from it (coin_counts, the new `files[]` breakdown from
  `scan-file-list-and-selective-actions`, the hidden-volumes report) --
  currently only returned in-memory by `find()`, never written to disk --
  and (b) any durable, discoverable INDEX of "which output_dirs exist and
  what scan they represent."
- `web/app.py`'s `_load_scan_results(output_dir)` (~line 1161) already
  loads balance-check results directly from disk, independent of any
  in-memory job -- it's already exactly the pattern this epic needs, just
  not applied to the Find stage's own summary yet.
- `web/findings.py`/`web/crawl_runs.py`/`tools/scan_index.py` are all the
  same established pattern to extend: sqlite under `app_data_dir()`,
  `_connect`/`_SCHEMA`/`_MIGRATIONS`.

## 3. My Proposed Approach

**`web/app.py`'s `_run_find_job`** writes the full summary dict (the exact
same one already returned to the caller -- `files_found`, `coin_counts`,
`total_address_instances`, `files[]`, `hidden_volumes_report`) to
`output_dir/find_summary.json` right after computing it. Trivial --
`json.dump`, no new computation.

**New `web/scan_history.py`** (sqlite, same pattern as
`findings.py`/`crawl_runs.py`): `record_scan(input_dir, output_dir)` --
just an index row (`{input_dir, output_dir, created_at}`), called from
`_run_find_job` alongside the summary write. `list_scan_history()` for a
new listing page. `clear_scan_history()` for the same reversible-vs-
destructive management pattern as every other list this session (this one
doesn't delete the underlying scan data on disk, just the index entry --
explicit in the UI).

**New route `GET /scans`**: lists every recorded scan, newest first --
input directory, when, files-found count -- survives every restart,
independent of any job still being in memory.

**New route `GET /scans/view`** (query param `output_dir`): loads
`find_summary.json` plus (if present) balance-check results via the
**existing, unmodified** `_load_scan_results(output_dir)`, and renders
through the same content `scan.html`/`scan_balances.html` already show --
this becomes the "come back anytime" durable view, with the same
selective-actions bulk toolbar from `scan-file-list-and-selective-actions`
wired against a durable `output_dir` instead of a live `job_id` (both
`scan_check_balances_selected` and `item_crawl`/`item_fork_coins` already
take plain paths/addresses, not job objects -- no backend change needed
there, just a second entry point into the same actions).

## 4. What This Does NOT Change

- `_load_scan_results()`, `check_wallet_balances()`,
  `run_pipeline.find()`/`check_balances()` -- reused unmodified.
- The existing `/scan/<job_id>` live-job flow -- untouched, still the
  fast path while a job is fresh in memory. `/scans` is an *additional*,
  durable way back in, not a replacement.
- `record_finding()`/`findings.db` -- already durable, untouched.

## 5. Risks

- **Disk growth**: every scan's `output_dir` (search/analyze/balance
  output) already accumulates on disk today, unbounded, independent of
  this epic -- not a new problem this creates. `clear_scan_history()`'s
  index-only clear (not deleting the actual `output_dir` files) is
  explicit about that scope, not silently promising disk cleanup it
  doesn't do.

## 6. Scale Assessment

**Small-to-medium.** One new sqlite module (index only, same established
pattern), one summary-file write (json.dump, no new computation), two new
routes reusing existing loaders/actions unmodified. Two stories: (1) the
durable summary write + index, (2) the `/scans` list + durable view page.
