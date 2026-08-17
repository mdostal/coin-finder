# Design Discussion: Bulk Private Key Extraction

## 1. What Are We Doing?

Right after reviewing tonight's credential-clarity-and-unlock-ux epic (the
"Check credential status" background scan that tells you, per Bitcoin
`wallet.dat` finding, whether a private key is structurally extractable --
unencrypted `key` record -- or genuinely encrypted -- `ckey` record, no
independent path around a password), the user's own words:

> "including, can we try to extract keys from MOST of them etc as well"

That epic built the *passive* signal: a badge saying "key extractable, no
password needed" per row. This ask is the *active* follow-through -- turn
that badge into a button. For every finding the cache already knows has an
extractable key, let the user run the extraction in bulk instead of opening
each one's "Extract key" form by hand.

This is not a from-scratch feature. Three pieces already shipped tonight do
all the hard work; this epic wires them together a third time:

1. `web/credential_scan_cache.py` already computes and caches exactly the
   candidate list ("which findings have an extractable key").
2. `web/app.py` already has the bulk-job pattern, proven twice tonight
   (bulk Try-unlock, bulk Check-credential-status).
3. `web/jobs.py`'s `secret=True` once-only result page, with ccu-01's
   eye-toggle mask, is the right home for showing a sensitive value
   exactly once.

The design judgment is in how these three pieces combine, not in building
anything new underneath them.

## 2. What I Found

### Extraction cost, read end to end

`extract_wif_for_address()` (`tools/extract_private_key.py:188-245`) calls
`find_key_value_pair_for_address()` (`:13-89`) to locate the target
address's record. That function is **not** an indexed lookup into anything
the cache stores -- it walks every BDB leaf page of the wallet file from
the top (`for page_base in range(page_size, wallet_file_size, page_size)`,
`:40`), decoding every `key`/`ckey` item and deriving its address, the same
page-walk `scan_wallet_key_types()` (`credential_scan_cache.py:61-108`)
does for the original scan. It returns as soon as it finds the matching
address (`:74`), so one call's cost is bounded by *where in the file* the
address sits, not always the full file -- but there is no cheaper path: the
cache (`credential_scan_addresses`, `credential_scan_cache.py:36-41`)
stores only `(wallet_path, address, key_type)`, deliberately no file offset
("Deliberately NO column anywhere for actual key material," `:25-28`), so
knowing an address is extractable doesn't tell this function *where* to
jump.

**Consequence for bulk:** extracting several addresses out of the *same*
wallet file means calling `extract_wif_for_address()` once per address,
each call independently re-walking that file's leaf pages from the start.
The original scan records every address's key-type in one linear pass
(`scan_wallet_key_types`'s own docstring, `:82-86`); extracting 5
addresses out of one wallet is up to 5 full-file passes, not 1. So bulk
extraction is **not** cheaper than the original scan once multiplied by
findings-per-wallet -- if anything it's more expensive in aggregate. It
still involves no decryption or brute-forcing (BDB parsing + DER decode +
address re-derivation only, same cost class ccu-03 already established),
and at this project's real scale (a handful of wallet files, a handful of
addresses each) the absolute cost stays small -- but the *shape* of the
cost means this must run through `run_job()`'s background-job pattern with
the same discipline as the original scan. It is not O(1) once the cache
says "extractable."

### `web/credential_scan_cache.py` -- the candidate list, already computed

`credential_status_index()` (`:211-248`) returns `{wallet_path:
{is_wallet_dat, scanned_at, error, addresses: {address: "key"|"ckey"}}}`.
This is already the exact shape needed: any `(wallet_path, address)` pair
with `addresses[address] == "key"` is a bulk-extraction candidate. `web/
app.py:669` already passes this whole index into `findings.html` as
`credential_status_by_path`, and `_macros.html:55-70`'s
`credential_status_badge()` macro already computes `key_type = wallet_scan.
addresses.get(address)` per row (`:56`) to render the badge (`:60`). No new
query is needed -- just exposing that same boolean as a selectable
attribute on the checkbox.

### The bulk Try-unlock pattern, traced end to end

- `findings.html:63` -- `bulk-try-unlock`, `type="button"`, not a submit.
- `findings.js:65-82` -- click handler collects `.bulk-select:checked`
  rows' `data-source-path` values and **navigates** (no job starts) to
  `/auto-unlock?wallet_path=...` with one repeated query param per wallet.
- `auto_unlock_form()` (`app.py:468-499`, GET) scopes the confirm page to
  those wallets, deliberately without calling `list_vault_entries()`
  inline (`:469-477` -- a documented prior blocking-call incident).
- `auto_unlock_submit()` (`:501-558`, POST) re-checks network status and
  vault-entries-exist at request time (never trusts the GET), then calls
  `run_job(_run_auto_unlock_job, ..., secret=True, kind="auto-unlock",
  ...)` (`:555-557`) and redirects to a status page.
- `auto_unlock_status()` (`:561-565`) polls via `poll.js`, then redirects
  to `auto_unlock_result()` (`:568-572`), which calls
  `consume_job_result()` once, ever.
- `_run_auto_unlock_job()` (`:1508-1550`) is the batch worker: iterates
  `wallet_paths`, builds a `{wallet_path: {vault_label, value}}` results
  dict.

Bulk `Check credential status` (`findings.js:44-53`, `app.py:719-747`) is
the *other* precedent, and the wrong one to copy here: it skips the
confirm page and starts its job from one POST because (per its own
comment, `:724-732`) it "never leaves the machine, never touches the
vault, and never reads private key material." Bulk extraction is the
opposite -- it reads real private key material, exactly the case the
offline gate exists for. The shape to replicate is **auto-unlock's**
confirm-then-job pattern, not credential-status's direct-POST pattern.

### ccu-01's eye-toggle -- reusable as-is

`web/static/secret-reveal.js` (all 36 lines) is generic: it keys off
`.secret-field` / `.secret-mask` / `.secret-reveal-btn` classes and a
`data-secret` attribute, with no reference to unlock or any specific
template. `auto_unlock_result.html:21-28` is the only current instance
(one row's Password column). A bulk-extraction result table needs the
identical markup, once per row, in a WIF column -- zero JS changes, a
template-only reuse.

Worth naming, not this epic's job to fix: the *single-finding*
`extract_key_result.html:14` (`<pre>{{ job.result }}</pre>`) still renders
its WIF in plaintext -- it predates ccu-01 and was never updated. The bulk
result page should ship with the eye-toggle from day one; backporting to
the single-finding page is a call for decomposition, not addressed here.

### `web/findings.py` -- no "already extracted" state exists today

`findings.py`'s schema (`:9-23`) has `coin, address, balance, source_path,
source_label, status, first_seen_at, last_checked_at, watched,
watch_note` -- nothing about credential or extraction state; that lives
entirely in the separate `credential_scan_cache` and `auto_unlock_history`
tables, joined into Findings by `source_path`/`address` at render time.
`record_finding()` (`:52-77`) never touches `status` on an existing row's
upsert and has no extraction-related parameter. Today, nothing
distinguishes "key extractable, never extracted" from "already extracted
and copied out" -- both render the identical badge. This mirrors exactly
the gap ccu-02 closed for unlock history (a separate table, joined by
`wallet_path`, not a `findings` column) and ccu-03 closed for credential-
completeness -- the natural next step is the same shape again.

### Existing test coverage

`tests/test_extract_private_key.py` (8 tests) covers the offline gate,
ckey-refusal, and end-to-end single-address extraction, but never calls it
twice against the same wallet or at "many addresses, one file" scale.
`tests/test_web_app_extract_key.py` (6 tests) covers the single-finding
form/submit/status/result flow only. `tests/test_credential_scan_cache.py`
(16 tests) covers the cache thoroughly but never as a bulk-extraction
candidate source. No test exercises a bulk job producing more than one
secret value on a once-only result page (auto-unlock's own result table
already supports N rows via its `{% for path, r in job.result.results.
items() %}` loop, so that part is precedented even though untested at
N > 1).

## 3. Proposed Approach

**Candidate selection: server-recomputed from the existing cache.** Add
one more `data-*` attribute to the bulk-select checkbox
(`findings.html:99`) -- e.g. `data-key-extractable="1"` -- set from the
same `key_type` the badge macro already computes (`_macros.html:56`), so
checkbox and badge can never disagree. A new "Extract keys selected"
button (`findings.js`, click-to-navigate like `bulk-try-unlock`, `:65-82`)
filters checked rows to `data-key-extractable="1"` client-side, with the
same "none eligible" alert pattern already used for the Bitcoin-only and
wallet-path filters (`:33-37`, `:47-51`) -- e.g. "None of the checked
findings have a known extractable key -- run Check credential status
first if you haven't yet." The server route re-filters identically (never
trusts the query string): re-read `credential_status_index()` and drop any
requested pair that isn't `"key"` there, the same way `auto_unlock_form`/
`auto_unlock_submit` re-derive `scoped_wallet_paths` from `_known_wallet_
paths()` rather than trusting the request (`app.py:488-489`, `:516-517`).

No auto-triggered scan. A selection including never-checked (or
`ckey`/absent) findings simply excludes them via the filter above --
consistent with ccu-03's "Check credential status" being a separate,
explicit step, not something silently triggered by a different button.
Piggybacking extraction on a stale or missing scan would risk exactly the
state-3/state-4 confusion ccu-03's own doc flagged as its real hazard.

**The bulk job: copy auto-unlock's shape, not credential-status's.**
Because extraction reads real key material, it needs the offline gate and
an explicit confirm step, like auto-unlock and unlike credential-status.
Four routes mirroring `auto_unlock_form`/`_submit`/`_status`/`_result`: a
GET confirm page scoped to the selected `(wallet_path, address)` pairs
(hidden fields, address-plus-wallet since a wallet-only scope isn't enough
here -- extraction is per-address), a POST re-checking
`check_network_status()` exactly like `item_extract_key()` already does
(`app.py:584-599`) before `run_job(_run_bulk_extract_job, ..., secret=True,
kind="extract-key-bulk", ...)`, a status page reused via `poll.js`
unchanged, and a once-only result page.

The job worker mirrors `_run_auto_unlock_job` (`:1508-1550`), not a direct
per-route call to `extract_wif_for_address`: for each `(wallet_path,
address)` pair, catch `RuntimeError` per pair (ckey refusal, address
vanished since the scan, offline-gate refusal) into the results dict
rather than aborting the whole batch -- the same per-item try/except
discipline `scan_and_record_wallet` already uses (`credential_scan_cache.
py:154-174`). Results keyed `{(wallet_path, address): {"wif": str,
"error": str|None}}` rather than `{wallet_path: value}` like auto-unlock's,
since one wallet_path can legitimately produce several rows.

**Dedup:** de-duplicate the requested pair set before running (defends
against a double-submitted form more than real double-selection, since
`findings`' PK is already `(coin, address)`). Distinct addresses sharing
one `wallet_path` are *not* a dedup case -- each is a real, separate
extraction that must run -- see the cost discussion above for why that's
the one place "bulk" costs more, not less, than doing it one at a time.

**Result page: same eye-toggle, N rows instead of one.** Built the same
way as `auto_unlock_result.html` (`:13-35`) -- warning banner, one `<tr>`
per `(wallet_path, address)` pair, WIF through the identical
`secret-field`/`secret-mask`/`secret-reveal-btn` markup, masked by
default. Each row reveals independently already (per-`.secret-field`
lookup, `secret-reveal.js:17-18`) -- no bulk "reveal all," so the screen
never paints many real spendable keys at once from one click.

**"Already extracted": new persisted state, same shape as ccu-02/ccu-03's
precedent.** `credential_scan_cache.py`'s `_MIGRATIONS` list (`:44`) is
already scaffolded, currently empty, for this. Add a nullable
`extracted_at REAL` column to `credential_scan_addresses` (already keyed
`(wallet_path, address)` -- this feature's own granularity, no new table
needed), following `findings.py`'s own `_MIGRATIONS` precedent (`:32-35`).
The bulk job records a timestamp there on success -- never the WIF itself,
keeping the cache's "metadata only" discipline (`:25-28`) intact.
`credential_status_badge()` gets one more branch: `key_type == "key" and
extracted_at` renders a distinct "key extracted" state instead of "key
extractable, no password needed" -- the same kind of per-row historical
badge ccu-02 added for unlock attempts, now for extraction. Re-extraction
stays possible and safe (read-only, self-verifying) -- `extracted_at` is a
"this already happened" marker, not a lock.

## 4. Risks

- **Extraction cost is not O(1) once the cache says "extractable" -- it
  can be *more* expensive in aggregate than the original scan for wallets
  with several extractable addresses.** Not a blocker at this project's
  scale, but it means the background-job discipline this project already
  learned the hard way (`app.py:469-471`'s documented blocking-call
  incident) applies at least as strongly here -- there's no "it's cached
  now, so inline is fine" shortcut available.
- **A bulk once-only result page shows several real, spendable WIF keys at
  once.** Higher stakes than a single-item reveal: more value visible
  simultaneously, more risk from a screenshot or back-button mishap.
  Per-row masking (not a "reveal all" toggle) should be a hard requirement
  in the eventual story. Re-running the job if a key is missed is safe and
  idempotent (read-only, self-verifying, per `extract_wif_for_address`'s
  own docstring, `:200-203`), which takes some "one shot or it's gone"
  pressure off -- but the UI copy should say so, since the once-only
  banner's existing wording could otherwise overstate the stakes here.
- **Same wallet_path, multiple selected addresses = multiple independent
  full-file walks of one file in one job.** Not a correctness risk (each
  call is independently self-verifying), but a real efficiency one as
  wallet files or address counts grow. A future multi-target variant of
  `find_key_value_pair_for_address()` extracting several addresses in one
  pass is a legitimate follow-up, not required at today's scale, and would
  touch `tools/extract_private_key.py` itself (untouched by this design).
- **The candidate list is only as fresh as the last "Check credential
  status" run.** A selection mixing scanned and never-scanned findings
  must not silently attempt or silently skip the unscanned ones -- the
  alert copy above needs to fire for that case, not just "zero eligible."
- **A `ckey` row must never be attempted even if somehow requested** (stale
  client state, a crafted request). `extract_wif_for_address()` already
  refuses these hard (`:221-225`); the real risk is only in how the batch
  job surfaces that per-pair failure -- a clear per-row error, not an
  aborted batch or a silent drop.

## 5. Scale Assessment

**Small-to-medium**, smaller than credential-clarity-and-unlock-ux's #2.
Nothing touches `tools/extract_private_key.py` or `tools/scan_wallet_dat.
py` -- both reused read-only. The work: one migration-column addition to
`credential_scan_cache.py`'s already-scaffolded `_MIGRATIONS` list; four
new routes in `web/app.py` mirroring the `auto_unlock_*` routes near-
exactly; one job-worker function mirroring `_run_auto_unlock_job` at
similar length; one new button + click handler in `findings.js` mirroring
`bulk-try-unlock`; one more `data-*` attribute on the existing checkbox;
one new result template reusing `secret-reveal.js` unmodified; one new
branch in `credential_status_badge()` for the "key extracted" state. No
new JS files, no new reveal logic, no new safety primitive -- the offline
gate and once-only job class both already exist and are reused as-is. The
one piece of genuine new judgment is the cost-shape finding above (bulk
extraction from a shared wallet file costs more, not less, than the
original scan) -- worth a clear callout in the eventual story so it isn't
assumed away as "already cached, so it's cheap now."
