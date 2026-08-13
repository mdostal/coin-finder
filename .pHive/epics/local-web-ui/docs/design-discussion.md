# Design Discussion: local-web-ui

## Goal

One local web app that replaces "run 13 different CLI tools by hand in the
right order" with: pick a drive/directory -> scan -> browse everything found
(candidate wallets, balances, relationship graph, dormancy, hidden-volume
flags) in one place -> act on any item (attempt unlock, derive from a seed
phrase, check fork coins, crawl its transaction cluster) -> copy anything
worth keeping to a safe staging area. Runs as `python web/app.py`, opened at
`http://127.0.0.1:5000`. This is the last planned epic before the toolset is
considered a complete, usable product for the user's stated north star
(recover missed funds reliably, broadened to other hobbyists too).

## Approach

Flask app under `web/`, importing every `tools/*` function directly
in-process (no subprocess wrapping except where the tool itself already
subprocesses out, i.e. `unlock_wallet.py`/`unlock_exodus_wallet.py` shelling
to BTCRecover/hashcat -- that stays as-is).

**Page/flow model** (server-rendered Jinja2 + small polling JS, no SPA
framework, no build step):

1. **Scan** (`/`) -- pick a directory (text input + "browse" via a server-side
   directory listing endpoint, since a `<input type=file webkitdirectory>`
   only yields filenames, not a real absolute path usable by the Python
   tools). Kicks off the existing `run_pipeline.py` flow plus
   `detect_hidden_volumes.py` as one background job.
2. **Results** (`/scan/<job_id>`) -- polls job status, then renders: found
   wallet-like files (from search+analyze), balances (incl. inconclusive),
   relationship graph (reuse `render_graph_report`'s Markdown, rendered to
   HTML), hidden-volume flags. Every row is a candidate the user can act on.
3. **Item actions** (`/item/<...>/action`, POST, redirects back to results
   with a flash message) -- per found item, on-demand triggers for the
   standalone tools that don't belong in the default auto-pipeline:
   - `scan_wallet_dat.py` for a `.dat` file (full BDB enumeration)
   - `crawl_transaction_graph.py` for an address (co-spend clustering)
   - `check_fork_coins.py` for an address (BCH/BTG)
   - `find_seed_phrases.py` / `match_seed_phrases.py` for a directory/file
   - unlock (BTCRecover or hashcat, chosen by file type) -- see below
   - "stage for backup" -- `shutil.copy2` into the staging directory
4. **Unlock** (`/item/<...>/unlock`) -- dedicated page, not a generic action:
   shows the live offline/online status (re-checked server-side on page load
   and again immediately before running), a textarea for candidate
   passwords/phrases (written server-side to a local temp file, never placed
   in the URL or query string, never in a persisted job-history record), and
   a Run button that is server-side refused (HTTP 409 + explanation, not just
   visually disabled) when the machine is online.
5. **Google Drive scan** (`/drive`) -- separate entry point (needs one-time
   OAuth), otherwise identical results/actions flow once files land locally.

**Job runner:** in-memory dict + `threading.Thread`, one job at a time is the
realistic usage pattern (single user, one drive at a time) but nothing
prevents concurrent jobs -- no artificial serialization needed since every
underlying tool is already safe to run concurrently against different inputs.

## Risks

- **Unlock result exposure via HTTP.** Turning "print to my own terminal
  once" into "an HTTP response" changes the blast radius even when bound to
  localhost (browser history, devtools network tab, OS-level clipboard if
  copied). Mitigation: never persist the unlock result to disk/job-history;
  deliver it once; document in the UI itself (a banner on the unlock page)
  that the result is not saved and won't reappear after leaving the page.
- **Directory browsing endpoint is a path-traversal-shaped feature by
  design** (the whole point is letting the user pick any local directory,
  including old drive mounts). This is fine for a localhost-bound single-user
  tool but would be a real vulnerability if ever exposed beyond
  `127.0.0.1` -- mitigation: hard-fail startup (refuse to bind) if
  `--host` is passed anything other than `127.0.0.1`/`localhost`, so this
  can't be silently misconfigured into something remotely reachable later
  (e.g. by the future Electron wrapper or a well-meaning `--host 0.0.0.0` for
  testing from a phone).
- **Long-running jobs (transaction-graph crawl, full wallet.dat balance
  sweeps) hitting rate-limited public APIs** -- already a known, handled
  condition in the underlying tools (retry + inconclusive tracking); the UI
  just needs to surface "inconclusive, recheck later" rather than presenting
  it as a false negative.
- **Scope creep** -- 13 tools is a lot of surface to wire up. Mitigation:
  stories split by user-visible slice (scan+results first, then unlock, then
  staging, then the remaining on-demand tools as one batch), each shippable
  and independently useful, rather than one big-bang story.

## Dependencies

- `flask` -- new production dependency, added to `requirements.txt`.
- No new dependency for anything else; every tool this wires up already has
  its libraries installed.

## Open questions

- Electron wrapper: explicitly out of scope, confirmed by the user ("later
  gets wrapped in Electron by the user separately -- not part of this
  epic").
- Multi-user/auth: out of scope -- this is a single-operator local tool, same
  trust model as running the CLI tools directly.

## Verification strategy

- Flask route/unit tests via Flask's test client (`app.test_client()`) --
  no browser automation needed for route-level behavior (job creation,
  status polling shape, the offline-gate 409 refusal, path-traversal-guard
  on the directory-browse endpoint, localhost-only bind refusal).
- One smoke-level manual check: start the dev server, drive a real scan
  against a small local directory, confirm results render -- can't be
  fully automated within this environment's network sandboxing (the same
  constraint already documented for the balance-check tools' live tests).
- Existing `tests/test_cli_standalone_invocation.py`-style regression
  coverage is not needed here (this app is Flask-invoked, not
  standalone-CLI-invoked) but the new `web/app.py` gets its own
  `tests/test_web_app.py`.

## Scale assessment

**Large.** This is a new application layer (multi-file Flask app: routes,
templates, job runner, static assets) that integrates all 13 existing tools
and introduces a new safety-relevant surface (HTTP exposure of previously
CLI-only offline-gated unlock flows). Per protocol, Large scope requires a
structured outline and H/V (Horizontal/Vertical) planning regardless of
`--fast`/`--lite`. Given this session's established solo/no-live-teammates
adaptation (single agent implementing every story directly, TDD, one commit
per story, condensed ceremony), H/V planning below is done as a direct
vertical-slice decision rather than a separate live review round: build
**vertically** (one thin end-to-end slice -- scan to results page -- before
breadth), since the highest-risk unknown (does the job-runner/results-page
shape work at all end to end) is best resolved by one working slice, not by
building all backend routes before any frontend exists.
