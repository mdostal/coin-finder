# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

## [0.25.1] - 2026-08-14

### Fixed

- **The real Portunus is installable again -- correctly this time.**
  `github.com/mdostal/portunus` is public now, so
  `requirements-vault.txt` (`pip install -r requirements-vault.txt`) pulls
  it directly from GitHub, pinned to `v0.16.1`, instead of the broken PyPI
  pin removed in 0.25.0. Still fully optional -- `/vault` works with its
  local fallback either way.

## [0.25.0] - 2026-08-14

### Added

- **In-app update check** (`/update`) -- compares the running version
  (from CHANGELOG.md) against the latest GitHub release and, one click,
  fast-forwards the local checkout to it (`git fetch` + `git merge
  --ff-only`, so it refuses rather than clobbers if you've got local
  changes). Doesn't restart the app for you -- re-run `python web/app.py`
  after updating.
- **One-shot local installer** (`scripts/install.sh`) -- creates a `.venv`
  and installs `requirements.txt` into it, run from an already-cloned
  checkout (deliberately not a `curl | bash` -- this tool handles private
  keys, so it gets the same "read it first" treatment the README asks of
  every third-party wallet tool). Verified end-to-end in a throwaway clone.

### Fixed

- **`requirements.txt` no longer references a broken `portunus` pin.**
  The real Portunus (this project's optional password-vault backend) isn't
  published to public PyPI -- the `portunus` package that *is* on PyPI is
  an unrelated project, so `pip install -r requirements.txt` failed for
  literally every install except this author's own machine (which has it
  installed as a local editable checkout). Portunus integration was always
  optional with a working local fallback (`web/vault.py`); the
  `requirements.txt` entry was simply wrong. Removed, with a README note
  on installing Portunus yourself if you want it.

## [0.24.0] - 2026-08-14

### Added

- **GitHub Pages landing page** (`docs/index.html`) -- a public, "ready to
  advertise" page for the project: what it finds (20 supported
  cryptocurrencies), the safety guarantees (offline-by-default, file-only
  secrets, once-only results, no unverifiable binaries), the full 15-tool
  toolkit, and an install snippet. Uses the same dark/teal/gold palette and
  the new Loupe & Coin icon as the app itself. Enabled to serve from
  `main`/`docs`.
- **README "Support this project" section** rewritten with the standardized
  copy used across the author's other open-source projects.

## [0.23.0] - 2026-08-14

### Added

- **Real app icon.** The web UI now ships a proper favicon/touch-icon
  ("Loupe & Coin": a magnifying glass beside a gold coin, rendered with
  Gemini 2.5 Flash Image) instead of an emoji placeholder --
  `web/static/icon/` has the generated `favicon.ico` + PNG sizes.
  `assets/icon/icon-1024.png` holds the 1024x1024 master source for the
  future Tauri packaging step (`cargo tauri icon assets/icon/icon-1024.png`
  generates the full platform icon set from it directly).

## [0.22.0] - 2026-08-14

### Added

- **Native file/folder pickers ("Browse…") on every path input.** Direct
  follow-up to feedback that typing full paths by hand doesn't fit a tool
  meant for anyone to use. Every path field across Scan, Unlock, Extract
  Key, Drive, Targets, and the deeper on-demand tools now has a "Browse…"
  button that opens the real OS file picker (Finder on macOS via
  `osascript`; `zenity` on Linux, e.g. Dolphin-desktop users) and fills the
  field with the chosen path -- typing the path is still fully supported,
  this is a convenience on top, not a replacement. New `web/native_dialogs.py`
  + `/api/pick-path`.

## [0.21.0] - 2026-08-14

### Added

- **Password vault, backed by [Portunus](https://github.com/mdostal/portunus).**
  Save known/guessed passwords once under a label ("password-1", "grandpa's
  laptop guess"), then pick saved entries from a checklist on the Unlock
  page instead of retyping them every run. New `/vault` page to add/list/
  revoke entries -- metadata only (label, description, state), never a
  value. The unlock flow resolves selected entries to their real values
  entirely in local memory/temp files (same file-only-secrets discipline as
  everywhere else in this project), and the once-only unlock result page
  now says which saved label matched, if any, without ever storing that
  match anywhere. If Portunus isn't installed, a local `.env`-based
  fallback store is used automatically so the feature still works;
  `portunus` is now a bundled dependency (`requirements.txt`).

## [0.20.0] - 2026-08-14

### Changed

- **`/item/unlock` and `/item/extract-key` no longer hard-block running
  online -- they offer an informed choice instead.** Direct correction of
  an earlier decision: this project's own stated direction has always been
  to let the user choose between offline-only and online operation with
  full transparency about the tradeoff, not to force a hard refusal.
  OFFLINE remains the strongly recommended default (submitting without
  opting in still refuses with HTTP 409, unchanged), but an explicit,
  clearly-labeled checkbox now lets you proceed online anyway if you
  understand and accept the risk. `run_unlock`/`run_exodus_unlock`/
  `extract_wif_for_address` already supported this via their own
  `allow_online` parameter -- the web UI simply never exposed the choice
  until now.

## [0.19.1] - 2026-08-14

### Fixed

- **rclone/macFUSE install is now click-to-run in the app**, not a
  "open a terminal and run this script" instruction. Real product-direction
  correction: this project is heading toward a packaged, installable
  application for non-technical users, and a shell script never fit that.
  New `web.mounts.install_rclone()` runs the same two `brew install`
  commands directly, with real progress shown via the existing job
  infrastructure, triggered by an "Install now" button on `/mounts` and in
  the setup wizard. `scripts/install_rclone.sh` remains for the git-clone/
  developer path (documented, not primary). The one step that genuinely
  cannot be automated -- macOS's manual macFUSE security approval -- is
  unchanged either way and is explained on the result page.

## [0.19.0] - 2026-08-14

### Added

- **Persistent findings dashboard** (`/findings`, `web/findings.py`). Every
  scan's results used to live only in an in-memory job, gone on server
  restart, with no way to see the accumulated picture across many scans.
  New SQLite-backed store records every wallet/address/balance found by
  any scan (the default pipeline scan, `scan_wallet_dat.py`,
  `crawl_transaction_graph.py`, `check_fork_coins.py`), keyed on
  (coin, address) so re-scanning updates a finding in place. A one-click
  "archive all zero-balance findings" action supports the "move and
  archive all the 0s, then work on the rest" workflow this was built for
  -- directly motivated by the upcoming multi-day, multi-session Google
  Drive and physical-drive crawls. Archiving a finding never gets silently
  undone by a later re-scan.

### Fixed

- Two real test-isolation bugs caught while building the findings store:
  wiring it into existing job functions immediately leaked test fixture
  addresses into the real, persistent `web/findings.db`, and even a
  read-only `list_findings()` call created a stray real db file as a
  side effect of connecting to it. Both fixed with a new
  `tests/conftest.py` autouse fixture that patches both functions for the
  entire test suite -- verified the full run no longer touches
  `web/findings.db` at all.

## [0.18.0] - 2026-08-14

### Added

- **Private key extraction is now in the web UI** (`/item/extract-key`) --
  `tools/extract_private_key.py` was CLI-only until now, a real gap given
  it's the tool that actually unlocks this project's first confirmed real
  find. Same offline gate as the web unlock flow (re-checked server-side on
  every submission, refuses with 409 otherwise) and the same once-only
  result delivery (shown on a dedicated page exactly once, then deleted
  from server memory -- never reappears, never persisted).

## [0.17.1] - 2026-08-13

### Fixed

- **`find_seed_phrases.py` now skips binary files before the expensive
  checksum pass.** Discovered live during a real stress-test scan of this
  machine (a multi-hour run against ~85GB of mixed personal/dev files) --
  the per-word-window BIP39 checksum check was running against every
  file's content regardless of whether it could possibly contain a real
  phrase. A cheap pre-filter (null byte in the first 8KB -- the same
  signal `git`/`grep -I` use) skips binary files (photos, video, compiled
  binaries, archives) before tokenization/checksum work starts. Directly
  motivated by the upcoming much larger Google Drive and physical-drive
  crawls, where this would otherwise scale from hours to potentially
  weeks.

## [0.17.0] - 2026-08-13

### Added

- **Site-wide connectivity status + job progress.** A persistent nav-bar
  indicator (`GET /api/status`, reusing `check_network_status()` -- never a
  second implementation) shows OFFLINE/ONLINE/UNKNOWN on every page, not
  just the unlock page. Long balance-check jobs (the default scan, a full
  `wallet.dat` sweep) now report live progress (`checked N / M addresses`)
  via an additive `progress_callback=None` parameter threaded through
  `check_wallet_balances.py`, `scan_wallet_dat.py`, and `run_pipeline.py` --
  every existing CLI/test call site unaffected.
- **Saved scan targets** (`/targets`) -- bind a drive/directory once, reuse
  it with one click. Detects already-mounted volumes (macOS) so a
  just-plugged-in physical drive shows up ready to scan. Removing a target
  only ever forgets the saved reference, never touches the underlying
  files.
- **rclone-based Google Drive/GCS mounting** (`/mounts`,
  `scripts/install_rclone.sh`) -- for cloud storage too large to download
  first, mount it as a local-looking directory instead; the existing scan
  tools then just work against it, no new cloud-aware scanning code needed.
  Mounts are always read-only. Health-checked via real process/mount-point
  status, not just path existence, since a crashed FUSE mount is a known
  failure mode that silently reads as an empty (not broken) directory.
- **Guided setup wizard** (`/wizard`) -- "what do you want to scan?" routes
  to the right existing page (local scan form, detected volumes, or the
  Drive/GCS mounting walkthrough) with plain-language explanation at each
  step. Never reimplements scanning/mounting/binding, and never claims a
  step succeeded without that page's own real health check confirming it.
- Local web UI: second visual-design pass (nav wrapping, button hierarchy,
  a dashboard-style home page tying saved targets + wizard entry point
  together), a real favicon (emoji placeholder), and a real fix for
  `ui_output/` never having been gitignored in the first place.

## [0.16.0] - 2026-08-13

### Added

- **Bitcoin SV fork checking.** `tools/check_fork_coins.py`'s FORK_COINS
  list now includes Bitcoin SV (previously a stated gap) via a new
  `services/bitcoin_sv.py` (Blockchair, same pattern as Bitcoin Cash/Gold).
  Matters even for an address whose *current* BTC balance is zero: BTC
  spent *after* a fork's snapshot leaves the fork-coin balance untouched on
  that fork's own chain.
- **Feathercoin support.** New `services/feathercoin.py` (Trezor's
  Blockbook explorer, verified live against a real address before being
  trusted -- Chainz Cryptoid, this project's usual multi-coin API host,
  does not support Feathercoin at all) plus search keywords, so old
  Feathercoin wallet files can be found and their balances checked like
  every other supported coin.

## [0.15.0] - 2026-08-13

### Added

- **Private key extraction** (`tools/extract_private_key.py`). For an
  unencrypted Bitcoin Core `wallet.dat`, extracts one address's private key
  as a WIF string for import into a real wallet (Electrum recommended, via
  its own sweep function) -- built as the direct next step after this
  project confirmed a real 0.29999058 BTC balance sitting in an unencrypted
  wallet file. Same hard offline gate as `unlock_wallet.py`; never prints
  the key, only writes it to a local file; self-verifies by re-deriving the
  address from the WIF it's about to return and refusing on any mismatch.
  Deliberately stops at the WIF file -- transaction construction, signing,
  and broadcast are left to well-audited existing software, not new custom
  code in this project.

  Three real bugs were caught during this tool's own development, each
  found by testing against real wallet data before anything with an actual
  balance was touched: a BDB value/key pairing off-by-3 bytes; a wrong
  assumption about the key record's trailing byte structure (the real
  format is `compact_size(length) + DER + more metadata`, not a bare DER
  blob); and `cryptography`'s DER parser flatly refusing Bitcoin Core's own
  key encoding (explicit secp256k1 curve parameters, deliberately blocked
  by that library as an anti-footgun policy) -- fixed with a minimal,
  self-validating fixed-field extraction instead of a general-purpose
  DER/EC-key loader. Validated against 16 real, zero-balance addresses from
  the actual target wallet (16/16 round-tripped correctly) before this
  tool was considered trustworthy.

- **Wallet recoverability report** (`tools/generate_wallet_report.py`).
  Combines deterministic wallet-software identification (from file
  structure), encryption status, and on-chain dormancy for addresses of
  interest into one Markdown report, pointing back to
  `docs/wallet_recovery_reference.md` for the self-custody-vs-custodial
  judgment call this project's tools still can't automate.

## [0.14.0] - 2026-08-13

### Added

- **Local Web UI (`web/app.py`).** A local Flask app that ties every tool in
  this project (the default `run_pipeline.py` flow plus all 13 standalone
  tools) into one Disk-Drill-style browser experience: pick a drive or
  directory, run a scan, browse the results (balances, inconclusive
  balances, relationship graph, hidden-volume flags) in one page, then act
  on anything found -- a full `scan_wallet_dat.py` enumeration, a
  transaction-graph crawl, a fork-coin check, seed-phrase discovery/matching,
  an offline-gated unlock attempt (BTCRecover or hashcat), a Google Drive
  scan, or staging a file for backup. Run it with `python web/app.py` and
  open `http://127.0.0.1:5000`. An Electron wrapper around this app is a
  separate, later effort outside this project's own scope.

  **Every safety property built up over the course of this project carries
  through the new HTTP surface, unweakened:**
  - `create_app()` refuses to bind to anything but `127.0.0.1`/`localhost` --
    enforced in code, not just documented.
  - The offline gate for real password/seed recovery
    (`unlock_wallet.py`/`unlock_exodus_wallet.py`) is re-checked server-side
    on every unlock submission, not just at page load and not just via a
    disabled button -- refuses with HTTP 409, no subprocess invoked, unless
    the machine reads OFFLINE.
  - Candidate passwords/phrases are written to a local temp file
    server-side, never placed in a URL or query string, and that file is
    deleted the moment the job finishes.
  - An unlock result (which may itself be a found password) is delivered
    exactly once, via a dedicated result page, then permanently deleted from
    server memory -- the polling path used everywhere else in the app
    deliberately never carries it, so a background status poll can't
    silently consume it before a human actually sees the result page. This
    correction was found and applied mid-build, before any code shipped in
    the wrong shape -- documented in
    `.pHive/epics/local-web-ui/stories/lwu-03-unlock-workflows.yaml`.
  - `find_seed_phrases.py`'s web results go stricter than its own CLI: no
    phrase text at all, only counts and file locations, since a web job
    result lives in server memory rendered into a browser tab rather than a
    local output file only the user can read. `match_seed_phrases.py` keeps
    its existing rule (phrase text shown only for an actual balance match).
  - Staging a file is copy-only (`shutil.copy2`) and refuses to silently
    overwrite an existing same-named staged file.
  - The Google Drive entry point reuses `scan_google_drive.py`'s existing
    OAuth + direct-Drive-API-to-disk functions unchanged -- no
    reimplementation of the architecture built after this project's earlier
    live safety correction.

## [0.13.0] - 2026-08-13

### Added

- **Google Drive adapter.** New standalone tool `tools/scan_google_drive.py`
  slow-crawls Google Drive for wallet-like files (reuses `search_wallets.py`'s
  existing name/size heuristic) and downloads matches directly to local disk
  via the user's own OAuth credentials, so every other tool in this project
  can scan them like a local drive. Requires one-time Google Cloud OAuth
  setup (documented in README) -- this project cannot create those
  credentials on the user's behalf.

  **Built after a real, live safety correction found during development:** a
  metadata-only Drive search (safe) found real candidate files and a Google
  Doc titled "Circles wallet." Reading that doc's content through this
  session's *connected* Drive tools pulled a real, live 24-word phrase into
  the AI assistant's own context/transcript -- the same class of
  online-secret-exposure `unlock_wallet.py` and `unlock_exodus_wallet.py`
  are careful to avoid, via a different door. This tool's architecture is
  the fix: file content only ever flows through a standalone OAuth process,
  Drive-server to local disk directly, never through any AI-assistant
  context. Native Google Docs/Sheets/Slides are explicitly not
  auto-downloaded by this tool -- review those directly in Drive yourself.

## [0.12.0] - 2026-08-13

### Added

- **Exodus wallet unlock via hashcat.** New `scripts/install_exodus_tools.sh`
  installs [hashcat](https://hashcat.net/hashcat/) and fetches hashcat's own
  official `exodus2hashcat.py` extraction script into
  `vendor/hashcat-tools/`. New standalone tool
  `tools/unlock_exodus_wallet.py` wraps hashcat's native mode `28200`
  ("Exodus Desktop Wallet (scrypt)") to test candidate passwords against a
  real Exodus wallet's `seed.seco` file -- BTCRecover doesn't support Exodus
  at all. Reuses the exact same hard offline safety gate as
  `unlock_wallet.py` (v0.8.0): refuses to run unless the machine is verified
  offline. Tested only against hashcat's own official public example
  hash/password, not any real wallet.

## [0.11.0] - 2026-08-13

### Fixed

- **`BitcoinGoldService` pointed at the wrong host.** `check_balance()` was
  hitting Blockchair's webpage URL instead of its API URL, so every Bitcoin
  Gold balance check in this project's history silently returned `None`,
  indistinguishable from "no balance." Fixed to match `BitcoinCashService`'s
  already-correct pattern. First test coverage for any `services/*.py` file
  in this repo.

### Added

- **Fork coin checker.** New standalone tool `tools/check_fork_coins.py`.
  A hard fork copies the entire ledger, so any address that held BTC at a
  fork's snapshot controls the identical balance on the forked chain too,
  under the same private key -- free money to check for, no new derivation
  needed. Checks Bitcoin Cash and Bitcoin Gold (Bitcoin SV shares the format
  too but has no service here yet -- a stated gap). Composes directly with
  `scan_wallet_dat.py`'s and `crawl_transaction_graph.py`'s output.

## [0.10.0] - 2026-08-13

### Added

- **Multi-seed transaction-graph crawls.** `crawl_transaction_graph.py`'s CLI
  now accepts either a single address or a file of addresses (one per line),
  so a single run can mix addresses found on disk with addresses you
  currently hold/know about into one combined graph.
- **Wallet & service recoverability reference**
  (`docs/wallet_recovery_reference.md`, linked from the README). Explicitly
  scoped as a reference to cross-check against your own memory, not an
  automated classifier -- reliable "this address belonged to exchange X"
  detection isn't achievable from public blockchain data alone. Covers
  self-custody wallet software this project helps recover (Bitcoin Core,
  Electrum, Armory, more via BTCRecover) and well-known defunct custodial
  services, plus how this project's own dormancy/clustering output can help
  tell the two apart.

## [0.9.0] - 2026-08-13

### Added

- **Full wallet.dat key enumeration + balance scan.** New standalone tool
  (`tools/scan_wallet_dat.py`) parses a Bitcoin Core `wallet.dat`'s actual
  Berkeley DB structure to enumerate every address it contains, not just the
  ones a text regex happens to match. Real-world validation against a real
  wallet found 1016 unique addresses versus the 7 previously ever checked
  (0.7% prior coverage). If the wallet has encrypted (`ckey`) records, this
  tool still finds those addresses safely and reports that a password is
  needed to spend from them (see `unlock_wallet.py`).
  **Safety property enforced structurally, not just by convention:** every
  address needed lives in the database *key* half of each record; the
  *value* half, where private keys are stored, is skipped via position
  arithmetic and is never read from disk during a scan -- private key bytes
  never enter memory in the first place, this isn't a "don't print it" rule.
  `--limit` bounds a first pass since checking hundreds of addresses live can
  take a while.

## [0.8.0] - 2026-08-13

### Added

- **BTCRecover wallet-unlock integration.** New `scripts/install_btcrecover.sh`
  installs [BTCRecover](https://github.com/3rdIteration/btcrecover) (the
  actively maintained Python 3 fork -- the original `gurnec/btcrecover` is
  Python 2-only and no longer runs) into `vendor/btcrecover/`. New standalone
  tool `tools/unlock_wallet.py` wraps it to test candidate passwords against
  a real wallet file (Bitcoin Core, Armory, Electrum, and more).
  **Critical safety property:** the tool enforces BTCRecover's own documented
  "separation principle" (from its bundled `SKILL.md`, written for AI
  agents) with a hard gate -- it refuses to run unless the machine is
  verified offline, since a real recovery run must never happen on a
  network-connected session. Candidates are read from a file only, never a
  command-line argument. Tested only against BTCRecover's own public test
  fixture, not any real wallet.
- First Mermaid pipeline diagram in the README, showing how all nine tools
  relate.

## [0.7.0] - 2026-08-13

### Added

- **Seed-phrase HD derivation + balance matcher.** New standalone tool
  (`tools/match_seed_phrases.py`) turns a candidate seed phrase into an
  answer: derives addresses across a bounded set of known schemes
  (BIP44/BIP49/BIP84 for Bitcoin, BIP44 for Ethereum/Litecoin) via `bip_utils`
  (audited BIP32/39/44/49/84 library), and checks each against real balances
  using the project's existing balance-check services. Never computes or
  exposes a private key -- addresses only. Same secret-handling discipline as
  the seed-phrase finder: phrases are read from a file only (never a CLI
  argument), never printed to the console, and the report only repeats
  phrase text for phrases that actually produced a balance. v1's scheme
  coverage is intentionally bounded; a more exhaustive "deep dive" mode for
  exotic old-wallet schemes is planned as a future tool. (`seed-derivation-balance-check` epic)

## [0.6.0] - 2026-08-13

### Added

- **Seed-phrase finder.** New standalone tool (`tools/find_seed_phrases.py`)
  scans text files for candidate BIP39 backup seed phrases, using real
  checksum validation (`mnemonic` library, first production dependency added
  since kickoff) rather than just wordlist membership -- much fewer false
  positives than naive word-matching. Security-critical: found phrase text is
  never printed to the console, only written to the local output file, since a
  valid seed phrase is real private-key material. v1 is text-files only;
  OCR for image-embedded phrases is a known, explicitly deferred gap.
  (`seed-phrase-finder` epic)

## [0.5.0] - 2026-08-13

### Added

- **Dormancy/last-activity reporting.** `crawl_transaction_graph.py` now shows
  years-since-last-activity for every discovered address, with an explicit
  call-out on anything dormant 5+ years -- lets you verify your own
  assumptions about a wallet's history against the real blockchain record.

### Fixed

- **Standalone tool invocation.** Every `tools/*.py` that imports
  `config`/`services` (`search_wallets.py`, `analyze_wallets.py`,
  `check_wallet_balances.py`, `build_wallet_graph.py`,
  `crawl_transaction_graph.py`) now works when run directly as
  `python tools/foo.py ...`, per the README's documented usage. This was
  broken pre-existing (Python only puts the script's own directory on the
  import path, not the repo root) -- confirmed identically broken on
  `search_wallets.py`, so not introduced by recent epics.

## [0.4.0] - 2026-08-13

### Added

- **Blockchain transaction-graph crawler.** New standalone tool
  (`tools/crawl_transaction_graph.py`) that discovers other Bitcoin addresses
  likely owned by the same person, starting from one known address -- using
  only public blockchain data (no private keys). Uses common-input-ownership
  (co-spend) clustering as the primary, high-confidence signal, plus bounded
  output-following for lower-confidence "where did it go" discovery, guarded
  against mining-pool/exchange-style high-fanout transactions. Validated
  against a real found address -- discovered a second real address holding a
  non-zero balance. (`transaction-graph-crawler` epic)

### Fixed

- Confirmed (not yet fixed) a pre-existing bug: standalone tool invocation per
  the README (`python tools/foo.py ...`) fails for any tool importing
  `config`/`services` unless `PYTHONPATH=.` is set, because Python only puts
  the script's own directory on the import path. Reproduced on
  `search_wallets.py` too -- not introduced by recent epics. Tracked as a
  follow-up.

## [0.3.0] - 2026-08-13

### Added

- **Hidden/encrypted volume detection.** New standalone tool
  (`tools/detect_hidden_volumes.py`) flags files that look like VeraCrypt/
  TrueCrypt-style encrypted containers, using an entropy + magic-byte heuristic
  with no upper file-size bound -- built for scanning old hard drives and
  backups, not just small wallet files. Detect-and-flag only: prints manual-mount
  guidance and never attempts to guess, brute-force, or crack a password. Not
  wired into the default `run_pipeline.py` run -- invoked deliberately against a
  drive you suspect has a hidden container. (`deep-crawl-hidden-volumes` epic)

## [0.2.0] - 2026-08-13

### Added

- **Conservative balance-check retries.** Balance checks now retry up to 3 times
  (2s backoff) before giving up on an address, instead of settling on "no balance"
  after a single flaky API call. Addresses still inconclusive after retries are
  written to `inconclusive_balances.json` alongside `wallet_balances.json`, so
  they stay visible as "needs a recheck" rather than silently disappearing.
  (`conservative-balance-retries` epic)

## [0.1.0] - 2026-08-13

### Added

- **Wallet & coin relationship graph.** New pipeline stage
  (`tools/build_wallet_graph.py`) correlating discovered wallets/coins across
  every scanned file: duplicate-address confirmations, multi-coin file
  detection, and coverage-gap nudges. Runs automatically as pipeline stage 5,
  writing `wallet_relationships.json` and `wallet_relationships.md`.
  (`wallet-relationship-graph` epic)
- First test suite in the repo (`pytest`, dev-only dependency).
