# Design Discussion: Unlock Tools Packaging Fix

**Process note:** same no-live-teammates adaptation as every epic this
session. The most severe bug found this session: unlock has never
actually worked in any installed build. Discovered live, from the user's
own screenshot ("BTCRecover is not installed"), while investigating a
UI-discoverability complaint about auto-unlock.

## 1. What Are We Doing?

Two stacked, real bugs, both confirmed via direct reproduction against
the actual frozen build, that together mean **BTCRecover/exodus2hashcat
have never run successfully in any packaged build shipped this
session** (v0.31.1 through v0.45.1):

1. `vendor/btcrecover/` and `vendor/hashcat-tools/` were never bundled
   into the PyInstaller build at all -- confirmed via `find` on the real
   installed `.app`: zero files anywhere. `find_btcrecover_script()`
   always returned `None` in every frozen build, every unlock attempt
   failed with "BTCRecover is not installed."
2. Once bundled, a second, deeper bug: `run_unlock()`/`run_exodus_unlock()`
   invoke `[sys.executable, script.py, ...]` -- correct in a normal
   source/dev environment (`sys.executable` is a real Python
   interpreter), but in a FROZEN build `sys.executable` is the app's
   OWN binary, which only knows how to run itself
   (`packaging/pyinstaller/entrypoint.py`). Confirmed via direct
   reproduction: it crashed trying to `int()`-parse the script's path as
   if it were its own port-number CLI argument.

## 2. What I Found

- `packaging/pyinstaller/coin_finder_ui.spec`'s `datas` list never
  referenced `vendor/` at all -- only `web/templates`/`web/static`.
- Fixing (1) alone (bundling the vendor dirs as `datas`) surfaced (2)
  immediately on the first real unlock attempt against the rebuilt app.
- `runpy.run_path()` (the natural fix for "run a script without a real
  subprocess-capable interpreter") is not a drop-in replacement for
  `python3 script.py` -- confirmed live, three real gaps needed fixing
  in sequence:
  - it does not prepend the script's own directory to `sys.path`
    (`btcrecover.py`'s sibling-file import, `import
    compatibility_check`, failed without this).
  - PyInstaller's static import scanner cannot see imports inside a
    file loaded dynamically at runtime -- `multiprocessing` and
    btcrecover's own dependency tree were invisible to the bundling
    step until the vendored scripts were added (not as separate entry
    points, just for import tracing) to the same `Analysis()` call.
  - btcrecover spawns multiprocessing worker processes by re-invoking
    the same frozen executable with special bootstrap flags
    (`--multiprocessing-fork`, `-B`) -- without
    `multiprocessing.freeze_support()` called first, those flags get
    misinterpreted as "the script to run," crash-looping.
- Every one of these was found and fixed via real, live reproduction
  against the actual rebuilt frozen binary -- run against BTCRecover's
  own public test fixture (`bitcoincore-wallet.dat` /
  `btcr-test-password`, already used by the existing test suite), not
  assumed fixed after each code change.

## 3. My Proposed Approach

`coin_finder_ui.spec` gains `vendor/btcrecover`/`vendor/hashcat-tools`
in `datas`, plus a SECOND bundled executable
(`coin-finder-script-runner`, via PyInstaller's `MERGE()` -- a sibling
executable sharing the same bundled Python runtime, not a doubled
~150MB build) whose only job is
`runpy.run_path(script, run_name="__main__")` with `multiprocessing.
freeze_support()` called first and the script's own directory prepended
to `sys.path`. `tools/unlock_wallet.py` gains `script_runner_prefix()`
-- `[sys.executable]` unchanged in dev/source, `[<path to the sibling
runner exe>]` when frozen -- and both `run_unlock()`/
`extract_exodus_hash()` use it instead of a hardcoded `sys.executable`.

## 4. What This Does NOT Change

- `find_btcrecover_script()`/`find_exodus2hashcat_script()` -- unchanged,
  already correctly REPO_ROOT-relative (frozen or not).
- The actual BTCRecover/hashcat invocation arguments, the offline safety
  gate, the file-only-candidates discipline -- all untouched.
- Non-frozen (source/dev) behavior -- byte-identical, `script_runner_prefix()`
  returns exactly `[sys.executable]` as before when `is_frozen()` is
  False.

## 5. Risks

- **~70MB added to every build** (`vendor/btcrecover`) -- unavoidable;
  the alternative is a feature that has never worked at all.
- **A second bundled executable increases build complexity** -- mitigated
  by `MERGE()` (shared runtime, not duplicated) and by the fact this was
  verified against the real, complex case (btcrecover's multiprocessing
  workers) live, not just the simpler exodus2hashcat path.
- **`vendor/` is fetched at setup time, not committed** (per this
  repo's existing `.gitignore` convention) -- CI/fresh-clone builds
  still require `scripts/install_btcrecover.sh` to have run first; this
  epic doesn't change that precondition, only what happens once it has.

## 6. Scale Assessment

**Small in surface area, high in stakes and iteration count.** One
spec file, one new small runner script, two call-site changes in
`tools/`. Single story -- the fix was iteratively verified live against
the real frozen binary until a real password was actually found.
