# Design Discussion: Group-View Transaction Graph

**Process note:** same no-live-teammates adaptation as `transaction-graph-
crawler` and `wallet-relationship-graph` -- self-authored, no separate
researcher/tpm/architect dispatch. Grill/collaborative-review condensed into
this single self-review pass. Requested directly by the user mid-session
("after we build that -- we should do an AUTO show of the wallets and their
cluster on the chain... a GROUP view graph -- we have each one pulled
already -- and save data locally... let the user keep or clear runs").

## 1. What Are We Doing?

Every time someone clicks "Graph" on a Bitcoin finding (shipped this
session, v0.33.0), it crawls that address's transaction cluster but the
result evaporates once the job's in-memory record is gone. This epic: (1)
persist every crawl run's full result to disk, (2) build one merged view
across every saved run that surfaces addresses discovered by more than one
separate run -- the actual "these two found wallets are probably related"
signal -- and (3) let the user manage (view which runs exist, clear them).

## 2. What I Found

See research-brief.md. Key point: `crawl_wallet_cluster()` already returns
everything needed (`confidence`, `generation`, `balance`, `dormant_years`)
per discovered address; nothing new to compute, only to persist and then
diff against every other saved run.

## 3. My Proposed Approach

**New module `web/crawl_runs.py`**, sqlite-backed exactly like
`web/findings.py` (`_connect`/`_SCHEMA`/`_MIGRATIONS` pattern, own db file
`crawl_runs.db` under `app_data_dir()`):

- `record_crawl_run(seed_addresses, results, db_path=DEFAULT_DB_PATH)` --
  called from `_run_crawl_job` right after a crawl completes (alongside the
  existing `record_finding` loop, not instead of it). One row per run:
  `(run_id, seed_addresses_json, created_at)`; one row per discovered
  address per run in a child table: `(run_id, address, confidence,
  generation, balance, last_activity_timestamp, dormant_years)`. Two tables,
  not one denormalized blob -- keeps "which runs found address X" a plain
  indexed lookup instead of a JSON scan.
- `list_crawl_runs(db_path=...)` -- every saved run, newest first, with seed
  addresses and discovered-address count (for a management list).
- `find_overlap_addresses(db_path=...)` -- the actual group-view query:
  every address that appears in **more than one distinct run's** discovered
  set, grouped with which run(s)/seed(s) found it and at what
  confidence/generation each time. This is a plain SQL `GROUP BY address
  HAVING COUNT(DISTINCT run_id) > 1` -- no graph library, no new
  dependency.
- `clear_all_crawl_runs(db_path=...)` -- hard delete, mirrors
  `findings.clear_all_findings()` added this session.

**New route `GET /findings/group-view`** (`web/app.py`), new template
`web/templates/group_view.html`: a table of overlap addresses (address,
balance, which seed addresses/runs found it, confidence tags, dormancy),
sorted by balance descending like `render_cluster_report` already does. A
"No overlaps yet -- run Graph on a couple more findings" empty state (this
is expected and normal with only 0-1 saved runs). Reachable from
`findings.html`'s existing action bar.

**New route `POST /findings/group-view/clear`**: confirm-guarded (same
`onsubmit="return confirm(...)"` pattern as `findings_clear_all` this
session), calls `clear_all_crawl_runs()`.

**`_run_crawl_job` gets one new line**: `record_crawl_run(addresses,
results)` after the existing `record_finding` loop. No behavior change to
anything already shipped -- purely additive.

## 4. Why Not a Real Node-Graph Visualization

Explicitly out of scope per the user's own scoping note. A sortable overlap
table answers the actual question ("did two separate finds turn out to
share a cluster address?") without a new JS dependency, a layout algorithm,
or a whole rendering surface to maintain. If the table proves the concept
useful, an interactive graph is a natural, cleanly separable follow-up epic
-- not blocked by anything built here.

## 5. Risks

- **Only meaningfully testable with 2+ real crawl runs on hand.** The
  overlap query is simple SQL and unit-testable directly, but the
  live/manual "does this actually surface something interesting" check
  needs real data, which may not exist yet on this machine (only whatever
  Bitcoin findings + a real "Graph" click produced during this session).
  Mitigation: ship it regardless -- the value compounds as more crawls run
  over time, which is the whole point ("dig to the other hard drives and
  double down"). Not a blocker for correctness.
- **Schema growth on an already-migrated `findings.py` pattern.** Low risk
  -- this is a brand new db file, not another migration on the existing
  `findings.db`.

## 6. Open Questions

None blocking. Scale assessment below covers the one real judgment call
(scope size).

## 7. Scale Assessment

**Small.** ~3-4 files (`web/crawl_runs.py` new, `web/app.py` two new routes
+ one new call site, one new template, tests). Single layer (Flask +
sqlite + Jinja, the exact same shape as every findings.py change this
session). No cross-system migration, no new external dependency. Routing
per `/plan`'s own rules: design discussion is sufficient context --
proceeding directly to stories, no H/V planning, no structured outline.
