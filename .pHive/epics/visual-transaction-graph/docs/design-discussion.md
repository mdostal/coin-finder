# Design Discussion: Visual Transaction Graph

**Process note:** same no-live-teammates adaptation as every epic this
session. Second of a 3-epic technical track requested directly: "I still
haven't even been able to see the graph as it should run against the
fucking file and not me having to go do some stupid figuring out, it
should just let me choose, graph around it by x hops in both directions
sort of thing... Then when we have a bunch, it should auto be able to see
and help point out the wallets to follow and graph."

## 1. What Are We Doing?

Confirmed by direct code inspection: **there is no visual graph anywhere
in this app.** "Graph" (`tools/crawl_transaction_graph.py`'s
`crawl_wallet_cluster()`) already discovers a real BFS cluster --
co-spend + output-following, with confidence/generation/balance/dormancy
per address -- but `web/templates/item_result.html`, the page every crawl
job result renders through, does nothing with that data except dump a
plain-text report (`render_cluster_report()`'s string output) inside a
`<pre>` tag. The user has never actually seen a graph because one was
never built -- only a text report with the same name.

Two more gaps compound this: hop depth (`max_generations`, default 2) is
hardcoded with zero UI control, and `find_overlap_addresses()`'s
cross-crawl overlap detection (the "auto surface likely-related wallets"
ask -- already built, shipped as `group-view-graph` earlier this session)
is only reachable via one subtle text link on `findings.html`, never
proactively surfaced.

## 2. What I Found

- `crawl_wallet_cluster()` (`tools/crawl_transaction_graph.py:106`)
  returns `{address: {confidence, generation, balance,
  last_activity_timestamp, dormant_years}}` -- generation numbers exist,
  but **no parent/edge field**. The BFS loop
  (`crawl_transaction_graph.py:123-146`) knows exactly which frontier
  address led to each newly-discovered address (the outer loop variable
  `address`) but throws it away before storing. Drawing real edges (not
  just generation rings) needs one small additive field:
  `discovered_via: <parent address>` (`None` for generation-0 seeds).
- `web/app.py:290`'s `item_crawl()` route and `_run_crawl_job()`
  (`web/app.py:975`) call `crawl_wallet_cluster(seeds)` with no
  `max_generations` argument at all -- always the hardcoded default of 2,
  from the CLI's `--generations` flag down to nothing in the web path.
- `crawl_wallet_cluster()`'s BFS already follows **both** co-spend
  (same-transaction-input clustering) and output-following per hop --
  "both directions" is already structurally covered per generation; what
  was actually missing is showing it and letting the hop count be chosen.
- `web/app.py:995` already returns `{"report": ..., "results": results}`
  from `_run_crawl_job` -- the raw graph-shaped data is already computed
  and already flows to the job result. `item_result.html` just never
  reads `.results`, only `.report`.
- `find_overlap_addresses()` (`web/crawl_runs.py:125`, shipped this
  session) is real and correct -- the gap is purely surfacing: one
  `<a class="subtle">` link on `findings.html:17`, shown unconditionally
  regardless of whether there's anything to see.
- No existing JS graphing library is vendored in `web/static/` -- and
  given this whole app avoids external network dependencies by design
  (Google/CDN calls are explicit opt-in, never silent), a new dependency
  would need to be vendored locally with no CDN fetch. A hand-rolled
  Canvas renderer avoids that tradeoff entirely: the data model is
  already a tree (one parent per node, since `discovered[addr] =
  {...}` is set only the first time an address is seen), so a
  deterministic ring-by-generation layout (seed at center, gen-1 in a
  ring around it, gen-2 further out, etc.) needs no physics/force-layout
  library at all.

## 3. My Proposed Approach

**Story vtg-01 -- edges + configurable hop depth (backend):**
`crawl_wallet_cluster()` records `discovered_via` per address.
`item_crawl()`/`_run_crawl_job()`/the bulk "Graph selected" toolbar all
gain an optional hop-depth field (default 2, matching today's behavior
exactly when omitted; capped at a small sane maximum -- each extra hop
can multiply the number of real API calls, and this is a live network
crawl, not a local computation).

**Story vtg-02 -- the actual visual graph + surfaced overlaps
(frontend):** New `web/static/graph.js` -- a small vanilla-JS Canvas
renderer, no external library. Ring-by-generation layout (radius scales
with generation number), one line per node back to its `discovered_via`
parent, node color/size by confidence and balance, hover tooltip with
address/balance/confidence/dormancy, click-to-copy address.
`item_result.html` renders it when `job.kind == "crawl"` (feeding
`job.result.results` as JSON), falling back to the existing `<pre>`
report for every other job kind -- zero risk to any other tool's result
page. `findings.html` gets a real conditional banner (only rendered when
`find_overlap_addresses()` is non-empty) linking to group-view, instead
of an always-present subtle link -- the "auto surface" the request asked
for.

## 4. What This Does NOT Change

- `find_co_spend_addresses()`/`find_output_addresses()`/
  `fetch_address_transactions()` -- untouched, still the actual
  data-gathering logic.
- `render_cluster_report()` -- kept as-is; the text report still exists
  and is still what non-crawl callers (the CLI) see, just no longer the
  *only* thing the web UI shows for a crawl result.
- `find_overlap_addresses()`/`web/crawl_runs.py` -- untouched, reused
  exactly as shipped.
- Balance/confidence/dormancy computation -- unchanged; the visual layer
  only reads data that's already computed.

## 5. Risks

- **Hop-depth cap**: an unbounded generation count on a real BFS crawl
  against a live API is a real cost/time risk (every hop can multiply API
  calls against `max_addresses=200`'s existing ceiling) -- capped in the
  UI (e.g. 1-5) rather than left free-text.
- **Canvas rendering correctness** with real, messy data (dozens of
  addresses, ties in generation) -- mitigated by keeping the layout
  algorithm simple and deterministic (ring position = generation, angle =
  index within that generation) rather than attempting a general graph-
  layout algorithm.
- **Discovered-via ambiguity**: within one BFS generation, a `set()`
  frontier has no guaranteed iteration order, so which specific parent
  "wins" for an address reachable from two different frontier nodes in
  the same generation isn't deterministic across runs -- acceptable for
  visualization (still a valid tree edge, just not necessarily the same
  parent every time you re-run the same crawl), called out explicitly
  rather than silently treated as a non-issue.

## 6. Scale Assessment

**Medium.** One additive backend field + a UI form field (vtg-01,
small), one new static JS file + template branch + a conditional banner
(vtg-02, medium -- new rendering code, not just wiring). Two stories.
