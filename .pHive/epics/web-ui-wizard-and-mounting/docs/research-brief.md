# Research Brief: web-ui-wizard-and-mounting

## Requirement

Continue the local web UI (shipped as `local-web-ui`, v0.14.0, then visually
restyled this session) toward a real, approachable application:

1. Site-wide connectivity (online/offline) status, shown persistently, with
   full transparency about what that mode means for each feature.
2. A guided **setup wizard** that walks a non-technical user through
   attaching a scan target (local directory, mounted physical drive, Google
   Drive, or a GCS bucket) and explains what's happening at each step in
   plain language -- "makes it so any idiot can do this."
3. **Bound/saved scan targets** -- a persisted list the user builds once and
   reuses, plus detection of already-mounted volumes for a one-click "scan
   the whole drive."
4. **rclone-based mounting** for Google Drive and GCS buckets, so a
   multi-terabyte Drive doesn't need a full local download first -- once
   mounted, it's just another local-looking directory the existing scan
   tools already handle.
5. Continued visual/interaction polish -- live user feedback after the v1
   restyle (`web/static/style.css`, shipped this session) was "looking
   better, but still need another pass."

## Existing surface (what this builds on)

- `web/app.py` -- Flask app, all routes so far: `/`, `/api/browse`,
  `/scan` (+`/scan/<job_id>`), `/api/jobs/<job_id>`, five `/item/*` on-demand
  actions, `/item/unlock*` (offline-gated, once-only result), `/item/stage`,
  `/drive` (+`/drive/scan`). `create_app(host)` refuses non-loopback hosts.
- `web/jobs.py` -- in-memory job registry (`run_job`, `get_job`,
  `consume_job_result`); jobs are `{status, result, error, started_at,
  secret}`. **No progress field today** -- a job is only ever `running`,
  `done`, or `error`, with no intermediate progress signal. Tools like
  `check_wallet_balances.py`/`scan_wallet_dat.py` process addresses one at a
  time in a loop already -- a natural place to report incremental progress
  from, but nothing currently threads that back to the job registry.
- `web/static/style.css` + all templates -- v1 dark-theme restyle, shipped
  this session (`ffc6aa9`). Card layout, status pills, styled forms. No JS
  framework, no build step (explicit design decision from the `local-web-ui`
  epic, preserved since -- keeps a later Electron wrap trivial).
- `tools/unlock_wallet.py`'s `check_network_status()` -- the only place
  online/offline is currently checked, and only server-side inside the
  unlock flow. Nothing surfaces it elsewhere in the UI today.
- `tools/scan_google_drive.py` -- OAuth download-to-disk flow (unchanged by
  this epic; still the right tool for a Drive small enough to fully
  download). This epic adds a *second*, complementary path for Drives too
  large to download at all.
- `config/search.py` -- `os.walk`-based tools (`search_wallets.py`,
  `find_seed_phrases.py`) have no dependency on the underlying filesystem
  being local vs. FUSE-mounted -- they already work against any path that
  looks like a directory. This is why mounting (making cloud storage
  *look* local) composes for free with every existing scan tool, instead of
  needing new cloud-aware scanning code.

## rclone verified live (research, not assumed)

- `rclone` -- Homebrew-bottled, `brew install rclone` (1.75.0, no compile).
  Single tool for both Google Drive and GCS buckets (different `rclone
  config` remote types, same `rclone mount` command afterward) -- one
  install covers both cloud targets in the requirement.
- `rclone mount` on macOS requires **macFUSE** (`brew install --cask
  macfuse`), a kernel/system extension. **This one step cannot be
  automated** -- macOS requires the user to manually approve it in System
  Settings -> Privacy & Security (and typically a reboot on first install).
  The wizard must clearly explain and detect this step rather than silently
  assume it succeeded; a scripted install can get the user *to* that
  approval screen, not past it.
- `rclone config` (the OAuth/credential setup for a new remote) is
  interactive by design (opens a browser for Drive OAuth, or asks for a GCS
  service-account key) -- also not something to fully script blind. The
  wizard's job here is walking the user through it with plain-language
  explanation at each prompt, not eliminating the interaction.

## Open questions resolved during design

- **Wizard as guided existing-forms, not a new form system.** The wizard
  doesn't reimplement scanning -- it's a sequence of steps that (a) explains
  what's about to happen, (b) runs the relevant install/mount/OAuth command
  via the existing job-runner pattern, (c) on success, adds the result to
  the bound-targets list from story 2, and (d) hands off to the *existing*
  `/scan` flow. This keeps the wizard thin and avoids a second, parallel
  scanning implementation.
- **Bound targets storage.** A small local JSON file
  (`web/bound_targets.json`, gitignored -- it's local runtime state, not
  project source) holding `[{label, path, kind, added_at}]`. `kind` is one
  of `local`, `volume`, `gdrive-mount`, `gcs-mount` -- informational only,
  every kind is scanned identically once it's a filesystem path.
