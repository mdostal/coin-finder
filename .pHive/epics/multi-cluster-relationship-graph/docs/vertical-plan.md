# Vertical Plan: Multi-Cluster Relationship Graph

Medium scope — two sequential slices, each a working state.

## Slice 1 — Combined graph data + route (backend-complete, no overlap styling yet)

`get_runs_graph_data(run_ids)` in `web/crawl_runs.py` (§3.1 of the design
discussion): full node+edge set across selected runs, deduplicated,
SQL-first. New route serving this data as JSON/rendered graph, reusing
`graph.js`'s existing Cytoscape setup as-is (confidence/balance coloring
only, no overlap treatment yet). Working state: you can select 2+ runs and
see them combined in one real graph — the core ask — even before the
cross-group visual polish lands.

## Slice 2 — Cross-group overlap styling + entry point from the table view

Add the overlap-detection logic (§3.2: node appears in 2+ of the
*selected* runs) as a second, independent visual channel (border
treatment, not fill color) layered onto slice 1's graph. Add the tooltip
data showing which runs/seeds found an overlap node. Add the multi-select
+ "View combined graph" entry point to `group_view.html` (§3.4) so this is
actually reachable from the UI, not just a route you'd have to know the
URL for. Working state: the full feature as asked — combined graphs with
visible cross-sections, reachable from where a user would naturally look.
