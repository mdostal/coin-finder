# Design Discussion: Auto-Unlock Across All Wallets

**Process note:** same no-live-teammates adaptation as every epic this
session. Requested directly: "There should be a way to do an auto unlock
which tries all wallets, all keys, and maps them across." The most
security-sensitive epic this session -- touches the offline-gate-protected
unlock flow directly. Extra care taken below to preserve every existing
invariant, not just reuse the pattern quickly.

## 1. What Are We Doing?

The existing `/item/unlock` flow tests candidate passwords against ONE
wallet file per job. This adds a batch mode: every known wallet file
(from Findings' recorded `source_path`s) against every saved Vault entry,
in one run, producing a map of wallet -> matched password label (or "no
match"). Same offline gate, same file-only-secrets discipline, same
once-only result consumption as the single-wallet flow -- this is a loop
around the existing mechanism, not a new one.

## 2. What I Found

- `web/app.py`'s `item_unlock()` (~line 281) is the reference
  implementation for every invariant this must preserve:
  - **Offline gate**: `check_network_status()` re-checked at request time
    (never trusted from a prior page load), refuses with a real
    explanation unless `allow_online=1` was explicitly checked -- an
    informed override, never a silent bypass.
  - **File-only secrets**: candidates (free text + resolved vault values)
    are combined into one local temp file, never a URL/query param.
  - **Once-only result**: the job is created with `secret=True`, so
    `consume_job_result()` returns it exactly once then deletes it from
    the registry -- bounds a found password's exposure window.
- `tools/unlock_wallet.py`'s `run_unlock(wallet_path, candidates_file,
  allow_online=False)` and `tools/unlock_exodus_wallet.py`'s
  `run_exodus_unlock(...)` -- the actual attempt runners, unchanged,
  reused directly.
- `web/app.py`'s `_match_vault_label(stdout, vault_pairs)` (~line 904) --
  ephemeral, in-memory-only match of a found password back to its saved
  vault label, explicitly documented as "never persisted, matching the
  once-only-secret result discipline." Reused as-is.
- `_run_btcrecover_unlock_job`/`_run_exodus_unlock_job` (~line 917/930)
  each delete their OWN candidates file after one use -- fine for a
  single-wallet job, but auto-unlock needs the SAME candidates file
  (built once from every enabled vault entry) reused across every wallet
  in the batch. Rather than modify those two functions (touching the
  existing single-wallet flow is explicitly out of scope), the new batch
  job calls `run_unlock`/`run_exodus_unlock` directly in its own loop and
  owns its own single cleanup after the whole batch finishes.
- `web/findings.py`'s `list_findings()` includes a nullable `source_path`
  per row -- the "known wallet files" set for a batch is every distinct,
  still-existing `source_path` across findings (archived included --
  archived means "reviewed," not "not a real wallet file").

## 3. My Proposed Approach

**New route `GET /auto-unlock`**: shows the exact same offline-gate
banner/explanation as `unlock.html` (reused, not reworded), plus the list
of wallet files it would try (every distinct existing `source_path` from
Findings) and how many enabled Vault entries it would try against each.
Nothing runs on page load -- this is a preview/confirmation page, matching
`unlock.html`'s own "you decide" pattern.

**New route `POST /auto-unlock`**: same `check_network_status()` +
`allow_online` re-check as `item_unlock()`, byte-for-byte. Requires at
least one enabled vault entry (no free-text candidates for a batch run --
typing the same passwords in twice when they're already saved makes no
sense for this flow). Starts one `secret=True` job.

**`_run_auto_unlock_job(job_id, allow_online)`**:
```python
wallet_paths = sorted({f["source_path"] for f in list_findings(include_archived=True)
                        if f.get("source_path") and Path(f["source_path"]).is_file()})
vault_pairs = resolve_vault_entries_with_values([e["name"] for e in list_vault_entries()])
lines = [value for _, value in vault_pairs]
with tempfile.NamedTemporaryFile(...) as f:
    f.write("\n".join(lines))
    candidates_path = f.name
try:
    results = {}
    for i, wallet_path in enumerate(wallet_paths):
        report_progress(job_id, i, len(wallet_paths), wallet_path)
        runner = run_exodus_unlock if wallet_path.endswith(".seco") else run_unlock
        result = runner(wallet_path, candidates_path, allow_online=allow_online)
        results[wallet_path] = _match_vault_label(result.stdout, vault_pairs)
finally:
    Path(candidates_path).unlink(missing_ok=True)
```
Kind detection (`.seco` -> Exodus, else BTCRecover-style) mirrors how
Exodus wallets are already distinguished elsewhere in this project by
file extension, since a batch run has no per-wallet form field to ask.

**Results page**: reuses the once-only `consume_job_result()` pattern --
a wallet -> matched-label (or "no match") map, shown exactly once, same
as the single-wallet result page's own "this was your saved 'X'" reveal.

## 4. What This Does NOT Change

- The single-wallet `/item/unlock` flow -- completely untouched.
- The offline gate's behavior or wording -- reused, not rewritten.
- `_match_vault_label`'s ephemeral, non-persisted matching -- reused
  as-is.
- No new place a found password could end up logged, written to disk
  outside the existing temp-candidates-file pattern, or exposed more than
  once.

## 5. Risks

- **A batch run against many wallets takes proportionally longer** --
  same per-attempt cost as today, just looped. Progress reporting
  (`report_progress`) keeps it visible, matching every other multi-item
  job this session (crawl, fork-coins, dedup-index scans).
- **Kind auto-detection by extension could misclassify an unusually-named
  file.** Same risk profile as any heuristic; the single-wallet form
  still exists as the precise, explicit fallback for anything auto-unlock
  gets wrong.

## 6. Scale Assessment

**Small-to-medium.** One new route pair, one new job function (loop
around existing, unmodified runners), one new template pair (form +
results). Single story -- the safety-critical parts are all reuse, not
new design.
