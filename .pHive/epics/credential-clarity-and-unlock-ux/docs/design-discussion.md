# Design Discussion: Credential Clarity & Unlock UX

## 1. What Are We Doing?

Tonight's Findings redesign, auto-unlock bulk actions, and vault system
shipped -- using them raised three real follow-up asks, user's words:

1. *"AND I don't want to show the actual password that was there unless
   they click an eye to see it, we want the rest of info visible, but the
   password itself not"*
2. *"one of the questions I have, most of these I had just a password to
   the account, do we need a private key to unlock them as well? have we
   found that as well? we need to make it very clear what we have and
   what we can try to unlock or not"*
3. *"AND we need to be able to try to unlock all the ones and see -- i see
   the auto path for that, but we'll need another UI pass for the rest of
   this as we go to see"*

None of these are a from-scratch redesign. #1 is a display-gate fix on
pages that already exist. #2 needs real investigation -- it's a genuine
new signal, not just a UI tweak, and getting it wrong in either direction
is bad for a tool whose entire job is not missing a real recoverable
wallet. #3 needs the existing bulk-unlock job pipeline extended with a
persistent, per-finding view -- not a new unlock pathway.

## 2. What I Found

### Ask #1 -- password shown in plaintext on load

Two templates render a real secret value the instant the page loads, no
gate at all:

- `web/templates/auto_unlock_result.html:21-22` --
  `<strong style="color:var(--accent)"><code>{{ r.value }}</code></strong>`
  inside the per-wallet result table's Password column.
- `web/templates/vault_reveal_result.html:13` -- same pattern, `{{ value
  }}` rendered directly.

Both pages are already the deliberately-conservative *once-only* surface
(`web/jobs.py`'s `secret=True` job class: `get_job()` strips `result` in
terminal states, only `consume_job_result()` returns it, exactly once,
then deletes the job -- confirmed at `web/jobs.py:88-150`). So the
"only shown once, never persisted" guarantee the user already trusts
(`auto_unlock_history.py`'s own top-of-file comment: no column for the
raw value exists in the DB at all) is intact. The gap is narrower: even
on that one legitimate viewing, the value paints in plaintext with no
extra click, and the eye-toggle ask is specifically about that.

### Ask #2 -- credential-completeness indicator (the real investigation)

**`tools/extract_private_key.py`, read end to end.** It only works
against Bitcoin Core's own `wallet.dat` (BDB v9) format -- confirmed by
its dependency on `EXPECTED_MAGIC`/`decode_bdb_key_record` from
`tools/scan_wallet_dat.py` (`extract_private_key.py:9`). It does **not**
support Electrum wallets, Exodus `.seco` files, or any other coin's
wallet format this project handles. That's a hard scope boundary for
whatever indicator gets built: it can only ever be meaningful for a
subset of findings (Bitcoin Core `wallet.dat`-sourced), never universal.

Within that scope, `find_key_value_pair_for_address()`
(`extract_private_key.py:13-89`) walks every BDB leaf page in the wallet
file, decodes every `key`/`ckey` item, and derives each one's address
(`pubkey_to_address`) to find the one matching `target_address`. This is
a **full linear scan of the wallet.dat file** -- the same cost class as
the original `scan_wallet_dat.py` pass that found the address in the
first place, not a cheap indexed lookup. It involves no decryption and
no brute-forcing (no AES, no password guessing) -- BDB parsing + address
derivation, not "close to the full extraction" computationally -- but
it's not free, and cost scales with wallet-file size/page count, once
per `(wallet_path, address)` pair queried. There's no header flag or
cheaper shortcut that skips this: the wallet-level "is this wallet
encrypted" bit Bitcoin Core exposes is per-*wallet*, not guaranteed
per-*address* in these older formats, so the address-level scan is the
only reliable source.

Two outcomes once that scan completes: the address is in an unencrypted
**`key`** record -> `extract_wif_for_address()`
(`extract_private_key.py:188-245`) produces a spendable WIF with **no
password needed at all** (the strongest possible state, stronger than
"we have a matching password"); or it's in an encrypted **`ckey`**
record -> the function explicitly refuses (`:221-225`): *"this tool only
extracts from unencrypted wallets... Use unlock_wallet.py (BTCRecover)
to recover the password first."* For encrypted wallets, extraction is a
dead end without a password already in hand -- never an independent
path around needing one.

**`web/auto_unlock_history.py`.** Schema is `(run_id, wallet_path,
vault_label, matched, run_at)` (`:17-26`) -- scoped to **wallet_path**,
not an individual address/finding. `list_auto_unlock_history()` (`:73-
94`) is only called from `auto_unlock_history_page()`
(`web/app.py:932-933`), a standalone page. Grepped `web/app.py` and
`web/templates/findings.html` for `auto_unlock_history`/`matched`/
`vault_label` together: **zero hits in findings.html or findings.js**.
Findings has no join against this table -- a wallet already unlocked in
a past run looks identical to one never tried.

**`web/vault.py`.** Vault entries (`:41-104`) are **generic named
secrets** -- `name`, `description`, `state`/tags via Portunus -- with no
coin/wallet/address scoping field. Confirms the harder framing in the
brief: today there is no "a password *for this finding*," only "some
saved passwords that may or may not have been tried against this
wallet." The only attempted-and-matched record is
`auto_unlock_history`'s `matched`/`vault_label`, at wallet-file
granularity only.

**Net effect:** a finding's true credential state is really one of four,
and no single existing table or function answers all of it:
1. **Password known** -- `auto_unlock_history` has a `matched=1` row for
   this finding's `source_path` (cheap: an indexed DB lookup, already
   collected as a side effect of every past unlock run).
2. **Private key extractable, no password needed** -- this
   `source_path` is a Bitcoin Core `wallet.dat` AND this address is an
   unencrypted `key` record (requires the BDB scan above -- not cheap,
   not cached anywhere today).
3. **Encrypted, no known password** -- `wallet.dat`, address is a `ckey`
   record, no `auto_unlock_history` match -- genuinely locked, a real
   password guess is the only path forward (same BDB scan tells you
   this, as a negative result).
4. **Unknown / not applicable** -- no `source_path`, a non-BDB format
   (Electrum, Exodus `.seco`, other coins), or the file no longer exists
   on disk -- extraction can't be evaluated for this row at all.

### Ask #3 -- bulk-unlock result surface

Traced the full path: Findings' "Try unlock selected"
(`findings.js:48-65`) collects checked rows' `data-source-path` values
and navigates (no job started yet) to `/auto-unlock?wallet_path=...`
(repeated param) -- `auto_unlock_form()` (`web/app.py:462-493`) scopes
the confirm page to just those wallets. Submitting POSTs to
`auto_unlock_submit()` (`:495-552`), which starts one `secret=True` job
via `_run_auto_unlock_job` (`:1438-1480`) and redirects to
`/auto-unlock/status/<job_id>`. `auto_unlock_status.html` polls
(`poll.js`) until done, then redirects to `/auto-unlock/result/<job_id>`
-- `auto_unlock_result.html`, the once-only table (per Ask #1 above).
`_run_auto_unlock_job` does call `record_auto_unlock_run()`
(`:1479`) at the end, so the wallet-path/matched/label metadata survives
into `auto_unlock_history` after the once-only page is gone.

What's missing, concretely: after that one viewing, the **only** way to
look back at a bulk run's outcome is the separate History page
(`/auto-unlock-history`), which is wallet-path-scoped, not linked from
Findings, and not filterable to "just my last batch" or "just this
finding." Findings itself carries zero visual trace of a prior attempt
-- a wallet tried and failed, a wallet tried and matched, and a wallet
never tried all render identically today. For a "run it against
everything, then come back later and see what happened" workflow
(exactly what Ask #3 describes), there's no persistent per-row status,
only a transient per-job one.

### Existing test coverage (so nothing here is a guess)

`tests/test_web_app_auto_unlock.py` (19 tests) already locks in the
once-only guarantee and the wallet_paths-scoped bulk flow -- the exact
plumbing #3's status UI should build on, not replace.
`tests/test_extract_private_key.py` (7 tests) covers the offline gate,
the ckey-refusal path, and end-to-end unencrypted extraction, but
nothing exercises calling `find_key_value_pair_for_address`
speculatively/at scale -- nothing in the app does that today.
`tests/test_vault.py`, `tests/test_auto_unlock_history.py`,
`tests/test_web_app_extract_key.py` cover their modules in isolation;
none test cross-referencing vault entries, auto-unlock history, and
Findings rows, because that join doesn't exist yet.

## 3. Proposed Approach

**#1 -- eye-toggle, straightforward.** Render the value into a
`data-secret` attribute (or a hidden sibling node) instead of directly
into visible text, with a small reveal button that swaps a masked
placeholder (`••••••••`) for the real value client-side, no new request.
No change to the once-only guarantee or the job/consume_job_result
plumbing -- purely a template + a few lines of JS in both
`auto_unlock_result.html` and `vault_reveal_result.html`. Worth deciding
once whether reveal also auto-re-masks after a timeout or on navigating
away (leaning yes, for the same "don't leave secrets on screen longer
than needed" spirit as the once-only page itself) but that's a small
follow-on choice, not a design risk.

**#2 -- credential-completeness indicator: cached, not live-per-row.**
State 1 (password known) is a cheap DB lookup against
`auto_unlock_history`, joinable to Findings by `source_path` with no
schema change. States 2/3 (key extractable / genuinely
encrypted-and-locked) require the BDB scan -- real, non-trivial I/O per
distinct wallet file. Doing it inline on every Findings page load is the
same class of mistake this project already hit and fixed once
(`auto_unlock_form`'s own comment at `web/app.py:463-471` about
`list_vault_entries()` blocking the single-threaded server for 10-15s).
Recommend:
- A small new cache keyed by `wallet_path` (not per-address -- the scan
  walks the whole file and can record every address's key-type in one
  pass) -- either a new table alongside `auto_unlock_history.py`'s
  pattern, or a `key_scan_status`/`key_scan_at` column on the existing
  findings schema. Wallet files don't change once discovered, so this
  is compute-once, reuse-forever -- only re-run if the user explicitly
  re-scans or the cached row is missing.
- Populate lazily via a background job (same `run_job()`/`secret`
  pattern already used for extract-key and auto-unlock), triggered by
  an explicit Findings action ("Check credential status," mirroring
  "Try unlock selected") or automatically the first time a
  `wallet.dat`-sourced finding is recorded -- **not** synchronously on
  page render.
- Scope honestly: only compute/show it for Bitcoin-`wallet.dat`
  findings -- state 4 is the default badge for everything else
  (Electrum, Exodus, other coins), never a false "unknown, treat as
  locked."
- Badge combines both signals per row: "Password known" (state 1,
  cheap, genuinely live) layered with "Key extractable / Encrypted, no
  password yet / N/A" (cached scan, states 2-4) -- two independent
  facts, not collapsed into one, since a wallet can have a known
  password AND unencrypted keys for other addresses in the same file.

**#3 -- bulk-unlock status UI, extends the existing pipeline.** Don't
build a second unlock pathway. Two additive pieces on top of what
already exists:
- After a bulk job completes and its once-only result page has been
  shown, surface a persistent, batch-scoped summary sourced from
  `auto_unlock_history`'s `run_id` grouping (`list_auto_unlock_history()`
  already returns exactly this shape, per-run, wallets-within-run, in
  order) -- e.g. a "view last batch result" link/banner on Findings
  itself after a bulk Try-unlock, rather than requiring a trip to the
  separate History page.
- Add a per-finding status badge on Findings (small, next to the
  existing status pill) driven by the most recent `auto_unlock_history`
  row for that finding's `source_path`: "unlocked" / "tried, no match" /
  "not yet tried" -- this is the cheap, always-live half of the #2 join
  described above, reused here for its own sake.

## 4. Risks

- **Getting #2 wrong in either direction is the real hazard.** A false
  "unlockable" badge sends the user to spend real time (and, for
  password attempts, real BTCRecover wall-clock) chasing a wallet that
  isn't actually accessible. A false "not unlockable" -- or defaulting
  unscanned/unknown wallets to a "locked" look rather than a distinct
  "not yet checked" look -- risks the user skipping past a wallet they
  genuinely could recover, which is worse for this tool's actual purpose
  than either a UI regression or extra manual work. The state-4
  "unknown/not applicable" bucket must be visually distinct from
  state-3 "checked, genuinely encrypted" -- collapsing them into one
  "can't unlock" badge would recreate exactly this failure mode.
- **The BDB scan is real, non-zero cost at the file level**, and this
  project's own comments (`web/app.py:463-471`) already document a
  concrete prior incident of an inline blocking call freezing the
  single-threaded server -- the caching/background-job approach isn't
  optional caution, it's avoiding a bug this project has already hit.
- **Scope creep risk on #2**: it would be easy to quietly promise "we
  tell you what's unlockable" for every coin/format this project
  supports. `extract_private_key.py` is Bitcoin Core `wallet.dat`-only
  -- the design and the eventual story writeup need to keep saying so
  explicitly, the same honesty `candidate-match-integrity`'s design doc
  used for its own coin-coverage split.
- **Vault entries and `auto_unlock_history` are both wallet-scoped, not
  address-scoped.** "Password known" only ever means "a saved vault
  password matched in a past run against this `wallet_path`," never
  "guaranteed for this address specifically"; a badge join for
  multi-address wallets will show the same "unlocked" status for every
  finding sharing that file, which is correct (one password unlocks the
  whole wallet) but should be called out in the story, and badge copy
  should say "wallet," not "address," to stay accurate.

## 5. Scale Assessment

**Medium.** #1 is small (two templates + a little JS, no backend/schema
change). #3's persistent per-row badge and batch-summary banner are
small-to-medium, built entirely on data `auto_unlock_history` already
collects -- no new job type, just new read paths and Findings template
work. #2 is the epic's real weight: a new cache/table, a new background
job (reusing the existing `run_job()`/`secret` infrastructure, not
inventing new infra), a Findings-page join across three data sources
(`auto_unlock_history`, the new key-scan cache, `findings.py` itself),
and template/badge work with real design judgment on showing a
two-axis, four-state signal without confusing "a saved password matched
this wallet" with "we structurally found a usable key for this
address." Contained to `web/` (app.py, a new small module alongside
`auto_unlock_history.py`, `findings.html`, `findings.js`, the two
result templates) plus new tests per state -- no changes needed to
`tools/extract_private_key.py` or `tools/scan_wallet_dat.py`
themselves, both reused read-only. Worth decomposing #2 into its own
story separate from #1/#3 -- it's the one with genuine new-schema and
background-job decisions the other two don't need.
