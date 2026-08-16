# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

## [0.49.1] - 2026-08-16

### Changed

- **Balance checks are faster again.** Raised per-coin concurrency from 5
  to 15 -- 5 was a conservative guess, never checked against blockstream.info's
  real published rate limit (~50 req/s, shared globally). Live-benchmarked:
  15 more than doubles throughput over 5 with zero increase in errors.

## [0.49.0] - 2026-08-16

### Added

- **Search Gmail for wallet/exchange clues.** New Email page (`/gmail`)
  searches Gmail for old exchange signup/withdrawal emails, wallet
  mentions, and wallet-like attachments -- extends this project's search
  beyond disk/cloud storage to email. Connects via its own vault-bound
  OAuth flow (client id/secret and refresh token stored in Portunus, not
  a plaintext file); email body/attachment content flows straight from
  Gmail's API to local disk, never through an AI assistant's own
  context. Only sender/subject/date/matched-address (public info) is
  ever shown.

## [0.48.0] - 2026-08-16

### Fixed

- **Balance checks no longer tick one address at a time.** Concurrency
  used to stop at the coin boundary -- every address of the SAME coin
  (almost always mostly Bitcoin) still ran strictly serially in a single
  thread, while other coins' threads sat idle after finishing in a
  second. Every address is now its own task in a shared pool, capped at
  5 concurrent requests per coin so a real API doesn't get hammered.
  Also now resumable across a quit/update/crash, same as scans got in
  v0.47.0 -- confirmed balances aren't re-checked on the next run.

## [0.47.0] - 2026-08-16

### Added

- **Scans survive an app quit, update, or crash now.** A directory scan's
  file walk used to have zero checkpointing -- interrupting it (including
  for an update) threw away all progress, forcing a full restart from
  nothing. It now checkpoints every 200 directories or 20 seconds, and
  re-scanning the same folder picks up from where it stopped instead of
  starting over. The scan page also now surfaces any interrupted scan
  with a one-click Resume button.

## [0.46.0] - 2026-08-16

### Added

- **"Try unlock" right from Findings.** Every found wallet row now has a
  direct "Try unlock" link that jumps straight to auto-unlock scoped to
  that one wallet -- no more digging for a hidden all-wallets page and
  needing to already know the file's path. The scoped run tries only that
  wallet against your saved vault passwords.

## [0.45.2] - 2026-08-16

### Fixed

- **Unlock actually works now.** The most severe bug found this session:
  BTCRecover was never bundled into the packaged app at all, so every
  unlock attempt in every installed build failed with "BTCRecover is
  not installed." Fixed, then a second, deeper bug surfaced immediately
  once bundled -- a frozen build can't shell out to a helper script the
  way a normal Python install can -- also fixed. Verified live,
  repeatedly, against the real packaged app until a real password was
  actually found.

## [0.45.1] - 2026-08-16

### Fixed

- **Mounting a cloud drive actually works now.** Homebrew's macOS build
  of rclone does not support the `mount` subcommand at all -- every
  mount attempt failed immediately with a bare "ERROR" pill and no
  explanation. Switched to `nfsmount` (same rclone binary, no macFUSE
  approval needed) -- verified against a real Google Drive connection.
  Mount failures now show the real error inline instead of nothing.
  Also added a Browse button and a sensible default to the mount-point
  field.

## [0.45.0] - 2026-08-16

### Fixed

- **The transaction graph is now actually readable.** A real crawl with
  a few hundred discovered addresses used to render as an unreadable
  blob -- seed addresses stacked on top of each other, and every address
  found at the same hop-distance crammed onto one fixed-size ring with
  no way to zoom in. Replaced the renderer with Cytoscape.js (a real,
  established graph library) -- proper ring spacing at any node count,
  real zoom and pan, same hover-for-detail and click-to-copy as before.
  Planned and built via `/plugin-hive:plan` + `/plugin-hive:execute`
  (epic `cytoscape-graph-rebuild`).

## [0.44.0] - 2026-08-16

### Fixed

- **Google Drive/GCS connections that never actually finished are no
  longer invisible.** `rclone config create` writes a connection's
  config to disk before sign-in completes -- a failed or abandoned
  attempt used to leave a permanent, broken entry with zero way to
  detect or remove it. Every connection now shows real status
  ("connected" vs "incomplete"), and can be removed and retried directly
  from the Mounts page or the setup wizard -- no more needing direct
  file-system intervention to recover.
- A custom Google API client ID is now validated before attempting
  sign-in at all -- catches a value that isn't actually a real Google
  OAuth client ID immediately, with a clear explanation, instead of a
  confusing Google error page five minutes later.
  Planned and built via `/plugin-hive:plan` + `/plugin-hive:execute`
  (epic `cloud-connection-reliability`).

## [0.43.0] - 2026-08-16

### Added

- **Confidence-scored related-account suggestions.** Findings now
  surfaces a ranked list of candidate addresses directly linked to a
  known finding by real, distinct transactions -- co-spend evidence
  weighted highest, transfers lower, independent rediscovery by a
  separate crawl as a bonus. Every candidate shows its full evidence
  breakdown in words alongside a High/Medium/Low label, never a bare
  score -- these are candidates worth investigating, not confirmed
  findings. Reachable from a new banner on Findings, or directly at
  Findings -> Related accounts.
  Planned and built via `/plugin-hive:plan` + `/plugin-hive:execute`
  (epic `confidence-scored-related-accounts`, third of the technical
  track this session).

## [0.42.0] - 2026-08-16

### Added

- **A real visual transaction graph.** There has never been one before --
  every Graph crawl result rendered as plain text only. Crawl results now
  render as an actual graph: seed address at the center, discovered
  addresses in rings by hop distance, lines showing which address led to
  which, colored by confidence and balance, with hover detail and
  click-to-copy. The text report is still there too.
- **Configurable hop depth for Graph.** Previously hardcoded at 2 hops
  with no way to change it -- now a 1-5 selector on both the manual crawl
  form and the "Graph selected" bulk action.
- **Cross-crawl overlaps are now surfaced proactively.** Findings shows a
  banner linking to Group view whenever an address has been discovered by
  more than one saved Graph run, instead of requiring you to know a
  subtle link existed.
  Planned and built via `/plugin-hive:plan` + `/plugin-hive:execute`
  (epic `visual-transaction-graph`, second of a 3-epic technical track).

## [0.41.0] - 2026-08-16

### Changed

- **Balance checks now run different coins concurrently.** Every one of
  the ~21 configured coin services hits a distinct external API with no
  shared rate limit, but balance checks used to run through them fully
  serially -- one address at a time, for every coin, for every file. A
  large wallet.dat with 1000+ addresses now checks all its coins in
  parallel instead of one long single-file queue. Each coin's own
  addresses still run in order with the existing retry/backoff, so no
  single API gets hit any harder than before.
  Planned and built via `/plugin-hive:plan` + `/plugin-hive:execute`
  (epic `parallel-balance-checks`, first of a 3-epic technical track).

## [0.40.0] - 2026-08-16

### Added

- **Find results now survive an app restart.** Previously, a completed
  scan's file list and coin counts only ever lived in memory -- every app
  restart (including every update install) silently lost them unless a
  balance check had already run. Every Find now writes its results
  durably to disk, indexed in a new "Past scans" list (Sources -> Past
  scans) so you can always get back to what a scan found, with the same
  selective check-balances/graph/fork-coins actions available from there
  too.
  Planned and built via `/plugin-hive:plan` + `/plugin-hive:execute`
  (epic `durable-scan-history`).

## [0.39.0] - 2026-08-16

### Added

- **The Find results page now shows the actual files matched**, not just
  aggregate coin counts -- every file path with its per-coin address
  counts, sorted most-address-dense-file-first.
- **Selective actions on selected files.** Check checkboxes and either
  check balances for just those files (new, isolated from the full
  scan's own results -- never overwrites them), or graph/check-fork-coins
  their Bitcoin addresses directly, instead of only the previous all-or-
  nothing "check the whole scan" action.
  Planned and built via `/plugin-hive:plan` + `/plugin-hive:execute`
  (epic `scan-file-list-and-selective-actions`).

### Changed

- Sources nav tabs reordered: Scan first (the default action), Manage
  last.

## [0.38.1] - 2026-08-15

### Fixed

- **The auto-unlock page blocked on a vault round-trip.** Same root cause
  as 0.32.2's wizard-page fix, reintroduced live: `GET /auto-unlock`
  called `list_vault_entries()` inline for a display count, confirmed
  15s from this app's own subprocess context. Removed the inline call
  entirely -- the real vault-entries check already happens in the POST
  handler that starts the job, a less frequent action.

## [0.38.0] - 2026-08-15

### Added

- **Auto-unlock across all wallets.** New "Auto-unlock" page tries every
  enabled Vault password against every wallet file already recorded from
  a scan, in one run, and maps which one (if any) unlocked which wallet --
  instead of testing one wallet/password pair at a time. Every existing
  safety invariant is reused unchanged from the single-wallet Unlock flow:
  the same offline gate (with the same informed-choice online override),
  the same file-only-secrets handling, and the same once-only result
  delivery. The single-wallet Unlock flow itself is untouched.
  Planned and built via `/plugin-hive:plan` + `/plugin-hive:execute`
  (epic `auto-unlock`) -- the most security-sensitive epic this session,
  with extra design-discussion detail on exactly what must not change.

## [0.37.0] - 2026-08-15

### Added

- **Editable Vault entries.** Previously add/revoke only -- now each
  saved password's description can be edited in place via Portunus's own
  `retag` command, which never touches the underlying secret value.
  Planned and built via `/plugin-hive:plan` + `/plugin-hive:execute`
  (epic `editable-vault-entries`).

## [0.36.0] - 2026-08-15

### Added

- **Quick single-address balance lookup.** Pick a coin, paste an address,
  get the balance directly -- skips the file-scan pipeline entirely, for
  when you already know an address and just want it checked. Reuses the
  existing balance-check building blocks unmodified, records into
  Findings the same way every other check does.
  Planned and built via `/plugin-hive:plan` + `/plugin-hive:execute`
  (epic `quick-lookup`).

## [0.35.0] - 2026-08-15

### Added

- **Persistent, content-hash scan dedup index.** Scanning overlapping
  drives/backups no longer re-analyzes the same file twice -- a file's
  exact content is hashed and checked against every prior scan, so a
  backup copy at a different path on a different drive is still
  recognized and skipped, reusing its previously found addresses instead
  of re-running the regex pass. On by default for multi-drive/multi-day
  scanning sessions, with an opt-out checkbox and a confirm-guarded clear
  action on the home page.
  Planned and built via `/plugin-hive:plan` + `/plugin-hive:execute`
  (epic `scan-dedup-index`).

## [0.34.0] - 2026-08-15

### Added

- **Group view: cross-crawl overlap detection.** Every transaction-graph
  "Graph" run is now persisted in full (previously ephemeral -- gone once
  the job finished). A new Group view page (linked from Findings) merges
  every saved crawl run and surfaces addresses discovered by more than one
  separate crawl -- the actual "these two independently-found wallets are
  probably related" signal, e.g. a suspected mining wallet and its holding
  wallet showing up as neighbors from two different Graph runs. A table
  view for v1 (not an interactive node graph, by design -- answers the
  real question without a new JS dependency). Saved crawl-run history can
  be cleared independently of findings (confirm-guarded, never touches
  findings.db).
  Planned and built via `/plugin-hive:plan` + `/plugin-hive:execute`
  (epic `group-view-graph`) -- same self-authored, no-live-teammates
  adaptation as this repo's earlier `transaction-graph-crawler` and
  `wallet-relationship-graph` epics.

## [0.33.0] - 2026-08-15

### Added

- **Findings can now run deeper analysis directly, one click at a time or
  in bulk.** Every Bitcoin finding gets "Graph" (crawl the transaction
  graph outward -- co-spent and related addresses, balances, last
  activity) and "Check fork coins" (same address on Bitcoin Cash/Gold/SV)
  buttons, reusing the existing crawl/fork-check tools that previously
  required copy-pasting an address into a separate form. A bulk toolbar
  (shown whenever at least one Bitcoin finding exists) lets you check
  several findings and run either action across all of them as one
  background job.
- **Watch a finding, with a note, to track a hypothesis while scanning
  continues.** Mark any finding "&#9733; Watch" with a short free-text
  reason (e.g. "suspected mining-wallet chain -- small amounts in,
  transferred out in equal chunks, expecting a holding wallet"). Watched
  findings always sort to the top of the list and get a visual highlight,
  so a candidate worth tracking down doesn't get buried as more scans add
  rows.
- **Clear all findings**, for starting over cleanly -- separate from
  archive/unarchive (which stay reversible); this is a hard delete,
  confirm-guarded in the UI.

## [0.32.2] - 2026-08-15

### Fixed

- **The cloud setup wizard page took 15+ seconds to load, even after the
  0.32.1 hang fix.** Root cause wasn't a hang this time -- `portunus`
  itself is just slow (confirmed: 10-15s) when invoked from this app's own
  subprocess context, vs. instant from a normal terminal (looks like
  portunus's own agent-facing gating behavior, not a bug in it). The
  wizard page called `ai_assist.has_api_key()` inline, blocking the whole
  page's render on that one vault round-trip. Moved the check to its own
  endpoint (`GET /ai-assist/status`), fetched by JS after the page has
  already rendered -- the actual setup form (name a connection, pick a
  scope, connect) is usable immediately; only the small "Ask AI" panel
  waits on its own, independent of everything else on the page.

## [0.32.1] - 2026-08-15

### Fixed

- **The vault (Portunus) could hang the entire app indefinitely, freezing
  it for every request, not just the one that touched the vault.** Caught
  live, immediately after shipping 0.32.0's wizard: `web/vault.py`'s five
  `portunus` subprocess calls (`list`, `drop`, `state`, `resolve`) passed
  no `stdin=` and no `timeout=`. A subprocess spawned from inside the
  Tauri-managed sidecar inherits a piped stdin that never produces EOF; if
  `portunus` ever tries to read from it, that read blocks forever, and
  because the Flask dev server is single-threaded, one hung vault call
  freezes the whole app for everyone. Every call now passes
  `stdin=subprocess.DEVNULL` (so a read returns EOF immediately instead of
  blocking) and a 15s timeout (matching the same discipline this project
  already requires of every `requests.*()` call, for the same reason: a
  call with no way to fail must not be allowed to hang forever either).

## [0.32.0] - 2026-08-15

### Added

- **Real in-app wizard for connecting Google Drive/GCS -- no more "open a
  terminal and run `rclone config`."** The Mounts and Cloud setup pages
  used to hand off to a terminal for the one step that actually mattered.
  Now there's a real form: name the connection, pick an access level in
  plain English (read-only is the default and the recommendation -- this
  app never needs more), optionally supply your own Google API client
  id/secret, and click Connect. It runs `rclone config create` as a
  background job; the one unavoidable manual step (Google's own sign-in
  and "Allow" screen) opens in your actual default browser -- not inside
  the app window, thanks to the 0.31.1 navigation fix -- and comes back on
  its own once you approve it. A client secret you provide is routed
  through the vault (Portunus) exactly like every other secret this
  project handles, never held in this app's own plaintext state.
- **Optional AI assist panel on the cloud setup wizard.** Bring your own
  Anthropic API key (stored in the vault, same as above) and ask a plain
  question about anything on the page -- client ids, access levels,
  whatever's unclear -- instead of guessing. Entirely optional; every step
  above works without it. Each question sends only your typed text plus a
  short fixed description of the wizard's own purpose, never wallet data;
  see the Network page for the exact accounting (`web/ai_assist.py`).

## [0.31.1] - 2026-08-15

### Fixed

- **External links (rclone.org, github.com, etc.) opened *inside* the app's
  own window, with no back button and no way out short of force-quitting.**
  The first attempt at a fix relied on JS calling
  `window.__TAURI__.opener.openUrl()`, which never actually worked: Tauri
  only injects that bridge into origins it trusts by default, and the page
  this app shows is served by its own local sidecar at
  `http://127.0.0.1:5050` -- a plain HTTP origin that doesn't automatically
  qualify, a known Tauri limitation
  (tauri-apps/tauri#7009, tauri-apps/tauri#11934). Reproduced and confirmed
  live before shipping this fix: the link opened in-window exactly as
  reported.
  Rewritten to intercept navigation on the **Rust side** instead
  (`on_navigation` in `src-tauri/src/lib.rs`): any navigation that isn't
  the bundled loading page or the sidecar's own origin is cancelled and
  handed to the OS default browser via the opener plugin, called directly
  from Rust. This doesn't depend on any JS bridge being present at all, so
  it can't have the same failure mode. The now-dead client-side
  interceptor (`web/static/external-links.js`) and its now-unnecessary
  `opener:default` capability permission were removed along with it.

## [0.31.0] - 2026-08-15

### Added

- **Scanning is now two independent stages: Find, then Check Balances.**
  Find (search + analyze) is fast -- no network calls -- and now shows real
  results immediately: files found, and a per-coin address-instance count,
  with a note that a huge count for a loosely-matching coin (OKCash,
  DigiByte, Ripple) usually means false positives, not real addresses.
  Check Balances (the slow part -- one real network call per address, with
  retries) only runs when you explicitly click "Check balances now," as
  its own background job -- so you can kick off another Find against a
  different drive while a previous Check Balances grinds through overnight.
  Direct fix for a scan that looked like it would "take 2 days" with zero
  visibility into what it had already found.

### Fixed

- **The balances/inconclusive/filtered results tables could 500 on real
  (non-empty) data.** `_load_scan_results` was handing `web/templates/
  _macros.html`'s `table()` macro a 3-level-nested dict
  (`{file: {coin: {address: balance}}}`); the macro expects a flat list of
  row dicts and indexes it like one (`rows[0]`), which raises on a real
  dict. Caught live, not by a unit test -- ran an actual scan through the
  UI. New `_flatten_balance_dict`/`_flatten_inconclusive_dict` fix it.

## [0.30.0] - 2026-08-15

### Changed

- **Nav groups (Sources/Unlock/About) now use real on-page tab strips**
  instead of hover dropdowns -- a dropdown made "About" and its "Network"
  item feel pointless since both landed on the same page. Tabs also fixed
  that directly: About's own tab order now puts Update first ("top of
  About"), so the About link and the Network tab go to different places.
- **The desktop build can now report its own version.** `/update` used to
  say "Couldn't determine the running version in this build" in the
  packaged app, since it has no `CHANGELOG.md` to read -- new
  `web/_version.py`, a plain committed module PyInstaller bundles
  automatically, is the fallback version source when the changelog isn't
  present.

## [0.29.0] - 2026-08-15

### Added

- **Real navigation redesign.** 10 flat top-level nav items collapsed to 4
  (Sources / Unlock / Findings / About), chosen from a multi-agent design
  pass (4 independent concepts, 3-judge critique, synthesized into 3 final
  options) -- picked the tightest of the three. Wizard, Targets, Mounts,
  and Drive now live as tabs under **Sources**; Vault and Extract Key now
  live under **Unlock** alongside Try; **Findings** is unchanged;
  Network and Update merge into **About**.
- **`/jobs` -- a real, durable page listing every background job** (scan,
  unlock, drive crawl, install) across every kind, with live status and a
  link back to each job's own detail page. Direct fix for "a scan looks
  cancelled once I navigate away from it": the truth about a job now lives
  somewhere with a fixed address, not just on the tab that started it. A
  small always-visible "N running" chip sits in the header on every page,
  linking here.

## [0.28.0] - 2026-08-15

### Fixed

- **Balance checks could hang forever, making a scan look "cancelled."**
  None of the 21 coin-service modules (`services/*.py`) passed a
  `timeout=` to `requests.get()` -- Python's `requests` has no default
  timeout, so a slow/unresponsive blockchain-explorer API could block that
  call indefinitely. This silently defeated
  `tools/check_wallet_balances.py`'s existing retry/inconclusive-balance
  handling, since a hung call never returns or raises for the retry loop
  to react to -- the scan just sat there with zero progress and zero
  error, forever. Caught for real: a live scan against a real directory
  sat unchanged for 30+ minutes with almost no CPU growth. Every
  `requests` call in `services/`, `tools/`, and `web/` now has a 15s
  timeout (`services.REQUEST_TIMEOUT_SECONDS`); a new test
  (`test_no_unbounded_network_calls.py`) statically checks every
  `requests.*()` call in the codebase for this so it can't regress.
- **Persistent app data (findings, saved targets, mount state, the vault
  fallback store, scan output) was being written inside the desktop app's
  own bundle**, which gets wholesale replaced on every reinstall/update --
  confirmed by finding `findings.db` and real scan output living under
  `Coin Finder.app/Contents/Resources/.../_internal/`, a location any
  future update silently wipes. New `web/paths.py` resolves persistent
  state to the OS's standard per-user app-data directory
  (`~/Library/Application Support/coin-finder/` on macOS) for a frozen
  desktop build, unchanged (`web/`) for a source install.

## [0.27.0] - 2026-08-15

### Added

- **`/network` -- a real, complete answer to "what does this app send over
  the network."** Every network call this codebase makes, in full, sourced
  from the actual code: the offline-status check itself (a bare TCP
  handshake to public DNS resolvers, no payload), balance checks (public
  address only, never key material), Google Drive scan (your own OAuth
  token, your own files), the update check (a version tag), and the
  vault (local only) -- plus an explicit statement that Unlock and Extract
  Key never send anything, ever, regardless of network status.

### Changed

- **Unlock/Extract Key's offline banners now explain the actual reasoning**
  instead of just saying "disconnect network" with no context: the offline
  recommendation is about *local* compromise risk (a candidate list and
  the real wallet file sitting together on a machine that can reach the
  outside world, if that machine were ever compromised), not a claim that
  this app would send anything anywhere. Links to `/network` for the full
  picture.

## [0.26.0] - 2026-08-15

### Added

- **Real macOS desktop app ("Coin Finder.app"), not just a clone-and-run
  script.** A Tauri v2 shell (`src-tauri/`) wraps the existing Flask app
  (frozen to a standalone binary via PyInstaller, `packaging/pyinstaller/`
  -- no Python install required) as a background sidecar and shows it in
  a native window. `frontend/loading.html` polls the new `/healthz` route
  until the sidecar is up, then hands the window off to the real UI.
  Quitting the app cleanly kills the sidecar and frees its port --
  verified directly (`lsof`) that the process the app spawns *is* the
  real Flask/Werkzeug process, not a bootloader wrapping it, so a normal
  quit (or a forced one) always frees port 5050. Built, ad-hoc signed,
  launched for real, and screenshotted showing the actual app UI (not
  stuck on the loading screen) before shipping -- see the release notes
  for the Gatekeeper caveat on an unsigned build.
- `web/app.py`: new `/healthz` route (zero I/O, just confirms the server
  is up) -- what the desktop shell polls.
- `web/update.py`: `get_current_version`/`perform_update` are now
  resilient to running outside a git checkout (a frozen desktop build has
  no `CHANGELOG.md` or `.git` to read) instead of 500ing -- caught by
  actually running the frozen sidecar standalone before wiring up Tauri,
  not assumed.

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
