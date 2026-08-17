# Design Discussion: Cytoscape Graph Rebuild

**Process note:** same no-live-teammates adaptation as every epic this
session. Direct bug report with a real screenshot: a 200-address crawl
result rendered as what looked like a single dot. Confirmed live against
the actual job data (not assumed) that all 200 nodes were genuinely
present -- the hand-rolled Canvas renderer built earlier this session
(`visual-transaction-graph` epic) just can't handle real cluster density.
User explicitly asked for research into existing tools before writing
more bespoke rendering code.

## 1. What Are We Doing?

Replacing `web/static/graph.js`'s hand-rolled Canvas renderer with
**Cytoscape.js** (MIT-licensed, vendored locally as a single ~425KB file,
no CDN/build-step dependency), using its built-in `breadthfirst` layout
-- which does exactly what the hand-rolled ring layout was trying and
failing to do (position nodes by hop-distance from a root), except with
proper collision-avoiding spacing, real pan/zoom, and real hit-testing,
none of which the hand-rolled version had.

## 2. What I Found

- Direct inspection of the real 200-node job that prompted this
  (`job.result.results`) confirmed: 2 seeds (generation 0), 9 at
  generation 1, 189 at generation 2 -- genuinely all present in the data,
  confirmed via `curl` + JSON parsing of the actual rendered page's
  embedded payload. The rendering, not the data, is what's broken.
- Root cause in the current `graph.js`: generation-0 nodes are placed at
  `radius = 0 * ringStep = 0` for every seed, so multiple seeds stack
  exactly on top of each other (looks like one dot even with 2 seeds);
  and every node at a given generation shares one FIXED radius
  regardless of how many share it -- 189 nodes at generation 2 all sit on
  one circle with no crowding-avoidance, overlapping into what reads as a
  blob or, depending on scroll position, nothing distinguishable at all.
  There is also no zoom/pan of any kind -- the canvas is a fixed
  900x600 with no interaction beyond hover/click on exact pixel
  positions.
- Researched real alternatives (WebSearch, current as of this session):
  for a graph capped at `max_addresses=200` (not a huge-graph case),
  **Cytoscape.js** is the right fit -- algorithm/layout-oriented,
  well-suited to moderate node counts, ships a genuine standalone UMD
  build (`cytoscape.min.js`) usable via a plain `<script>` tag with zero
  npm/webpack step, MIT license. Sigma.js (WebGL) is the right call at
  thousands+ nodes but is overkill and a worse fit for layout algorithms
  at our scale; vis-network is a reasonable second choice but Cytoscape's
  built-in `breadthfirst` layout is a more direct match for our
  hop-distance-from-seed model than vis-network's physics-first approach.
- Confirmed via `js.cytoscape.org` docs: `breadthfirst` and `concentric`
  are both CORE built-in layouts (no extension needed); pan/zoom are
  enabled by default (`panningEnabled`/`zoomingEnabled`); the standalone
  `dist/cytoscape.min.js` file is exactly the "download and vendor
  locally" artifact this project's no-CDN-dependency convention needs
  (downloaded and inspected directly -- 425KB minified, MIT license
  header confirmed).

## 3. My Proposed Approach

Vendor `cytoscape.min.js` at `web/static/vendor/cytoscape.min.js` (a new
`vendor/` subdirectory under `web/static/`, matching this repo's existing
top-level `vendor/btcrecover/` convention for third-party code kept
in-tree rather than fetched at runtime).

Rewrite `web/static/graph.js` around `cytoscape({...})`:
- `elements`: one node per discovered address (existing
  confidence/generation/balance/dormant_years data as node data), one
  edge per non-seed address using its `discovered_via` parent (already
  exactly the BFS tree edge -- no new backend work needed, `vtg-01`
  already produced this).
- `layout: { name: 'breadthfirst', roots: <seed addresses>, directed:
  true, spacingFactor: ... }` -- replaces every line of the old manual
  ring-position math. Cytoscape computes non-overlapping spacing itself,
  at any node count.
- Styling (node color by confidence/balance, size) ported directly from
  the existing `colorFor()` logic -- same visual language, just applied
  via Cytoscape's style API instead of manual `ctx.fillStyle`.
- Tooltip-on-hover and click-to-copy reused conceptually (same
  information, same interaction), wired through Cytoscape's own
  `node.on('mouseover'/'tap', ...)` events instead of manual pixel
  hit-testing.
- Pan/zoom are Cytoscape defaults -- no code needed for the core ask.

`item_result.html` swaps the `<canvas>` element for a `<div id="cy">`
(Cytoscape renders into a container div, managing its own internal
canvas/WebGL layer) and adds the vendored script tag before `graph.js`.

## 4. What This Does NOT Change

- The backend data model (`discovered_via`, `edges_out`,
  `crawl_wallet_cluster`) -- untouched, already exactly what this needs.
- `item_result.html`'s conditional gating (`job.kind == "crawl" and
  job.result.results`) and the text report shown alongside -- unchanged,
  same "augment, don't replace" decision as the original `vtg-02` epic.
- `findings.html`'s overlap/related-accounts banners, group-view,
  related-accounts page -- untouched, unrelated to this rendering swap.

## 5. Risks

- **Vendoring a new 425KB dependency** -- one-time addition, MIT
  license (compatible, permissive, no attribution-in-UI requirement
  beyond the license file itself which stays in the vendored file's own
  header), reviewed directly before inclusion (not blindly trusted).
- **Breadthfirst layout with 2 disconnected seed roots**: Cytoscape's
  `roots` option accepts multiple root nodes and lays out each
  root's reachable subtree correctly; verified against this exact
  real-world case (2 seeds) as part of live testing, not assumed.
- **Behavior for a node with no discovered_via edge reaching a root**
  (shouldn't happen given the BFS construction, but Cytoscape's
  breadthfirst layout has defined, sane behavior for disconnected
  components regardless -- it does not crash, just lays out
  disconnected pieces separately).

## 6. Scale Assessment

**Small-to-medium, single story.** One vendored file, one rewritten
static JS file, one small template change. The complexity is in getting
the layout/interaction right, not in surface area.
