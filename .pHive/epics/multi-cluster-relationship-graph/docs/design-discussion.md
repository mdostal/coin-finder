# Design Discussion: Multi-Cluster Relationship Graph

## 0. Prelude

Base branch: `dev` (established project convention). Research was a dedicated
pass against the live codebase (see §2), not reused guesswork.

## 1. Why now

User's own words, backlog item raised 2026-08-17: *"view related accounts
should also allow us to graph all of them together and see their clusters
and if there are cross sections and whatnot, i really care about seeing
multiple of them together there."*

Today the app can only ever show ONE crawl run's relationship graph at a
time, live, right after that specific job finishes (`item_result.html`).
There's a separate table view (`group_view.html`) that shows overlap
*addresses* across every saved run — but it's a table, not a graph, and it
was explicitly scoped that way on purpose: `group-view-graph`'s own design
discussion says a real graph was *"explicitly out of scope... a natural,
cleanly separable follow-up epic"* if the table proved useful. This is that
follow-up.

## 2. Ground truth: what exists today

- **`find_overlap_addresses()`** (`web/crawl_runs.py:245`) — a plain, fast,
  indexed SQL `GROUP BY address HAVING COUNT(DISTINCT run_id) > 1` across
  **every saved run globally**. Returns only addresses found by 2+ runs,
  discarding everything else, with no edges — built specifically to drive
  the existing overlap *table*, not reusable as-is for a real graph (a
  graph needs every node from every selected group, not just the
  intersection, plus the edge set).
- **No route renders a graph from persisted `crawl_runs.db` data at all.**
  The only existing graph route (`GET /item-result/<job_id>`) reads a live
  job's in-memory result, not a saved `run_id`. A multi-group graph needs a
  genuinely new route and a new run_id-parameterized query.
- **`web/static/graph.js`** (122 lines) already does real, working single-
  group Cytoscape rendering: confidence/balance-based node coloring
  (`colorFor`), a concentric layout deliberately chosen over breadthfirst
  after a live scale problem (a 189-vs-2 generation imbalance broke
  breadthfirst's ring spacing), hover tooltips, click-to-copy. This is
  directly reusable scaffolding, not something to rebuild.
- **Only Cytoscape core is vendored** (`web/static/vendor/cytoscape.min.js`,
  428K) — no compound-node/clustering extension. Both layouts in use today
  are core built-ins requiring no extension.
- **6 real runs exist today**, sizes 1 to 200 addresses (three runs hit the
  200-address cap). Combining 2-3 runs could realistically mean 400-600+
  raw nodes before dedup — squarely the scale the existing concentric
  layout was already built to handle (its trigger case was one 200-node
  run), but combining multiple such runs is a genuinely new scale point
  worth confirming, not assuming.
- **Established convention to preserve** (`confidence-scored-related-
  accounts`): a confidence label is never shown bare — always paired with
  the raw evidence counts that produced it. Any new overlap/cross-group
  signal should follow the same rule.

## 3. Proposed approach

**3.1 — New SQL-first query, not a reuse of `find_overlap_addresses`.** Add
`get_runs_graph_data(run_ids)` to `web/crawl_runs.py`: given a set of
selected run_ids, return every node from `run_addresses` across those runs
(deduplicated by address, keeping the highest-confidence/earliest-
generation record when an address appears in multiple selected runs) plus
every edge from `run_edges` filtered to those same run_ids — a real,
complete graph dataset, not just the intersection. Keeps the project's own
established precedent: plain indexed SQL, not Python-side JSON scanning.

**3.2 — Cross-group overlap as a second, independent visual signal.** A
node is "cross-group" when it appears in `run_addresses` for more than one
of the *selected* run_ids (a run_id-set-scoped sibling of
`find_overlap_addresses`'s globally-scoped idea, not a literal reuse).
Render this as a distinct visual treatment — e.g. a bold/dashed border —
layered on top of `graph.js`'s existing confidence/balance fill-color
logic, so confidence and cross-group-overlap read as two separate signals
a viewer can reason about independently, never conflated into one color.

**3.3 — New route + template, reusing `graph.js`'s scaffolding.** A new
route (e.g. `GET /findings/group-view/graph?run_ids=1,2,3`) renders a new
template built on the same Cytoscape setup `graph.js` already has —
extend, don't fork: add the overlap-border logic and multi-run tooltip
data (which run(s)/seeds found this node) to the existing coloring/tooltip
functions rather than duplicating the file.

**3.4 — Entry point from the existing table view.** `group_view.html`
already lists every saved run in its overlap table. Add a multi-select
(checkboxes per run) and a "View combined graph" action that navigates to
the new route with the selected run_ids — the natural, already-established
place a user would discover this from.

**3.5 — Tooltip convention preserved.** Clicking/hovering a cross-group
node shows which runs/seeds it was found in and why (same "never a bare
label" discipline as `compute_confidence_scores`), not just a colored dot.

## 4. Risks

| Risk | Mitigation |
|---|---|
| Combining 2-3 runs at 200 nodes each (400-600+ combined) may stress the concentric layout differently than one 200-node run did | Explicit manual scale check with the real 3 largest saved runs combined before considering this done — not assumed safe by extrapolation |
| Conflating "confidence color" and "cross-group overlap" into one visual channel would make the graph unreadable | Explicit design decision (§3.2): two independent visual channels (fill color vs. border treatment), never merged |
| Reusing `find_overlap_addresses`'s exact query as a shortcut would silently drop every non-overlapping node from the graph | Explicit decision (§3.1) to write new run_id-scoped query logic, not adapt the existing global one |

## 5. Scale assessment

**Medium.** Touches `web/crawl_runs.py` (new query function), `web/app.py`
(one new route), a new template + JS extension of `graph.js`, and
`group_view.html` (new multi-select entry point). Single-layer-ish
(backend query → route → frontend render), no new external service, no
new infra — real design work in the query/visual-encoding logic, but
contained to the existing crawl_runs/graph-rendering subsystem already
built out by two prior epics. Proceeding to H/V planning (multi-file,
worth slicing) without a full structured outline.
