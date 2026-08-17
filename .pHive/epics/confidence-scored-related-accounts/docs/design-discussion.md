# Design Discussion: Confidence-Scored Related Accounts

**Process note:** same no-live-teammates adaptation as every epic this
session. Requested directly, with real financial urgency: "please focus
around planning and executing this correctly to ensure we have this AND
can suggest with confidence scores likely other accounts or accounts
that had numerous transactions and interactions with our other
accounts." Correctness matters more here than in any other epic this
session -- a false "likely related" suggestion wastes real time in a
genuinely hard moment, and a missed one could mean missing real money.
Nothing here is presented as certainty; every score is a ranked,
transparent, explained candidate list, consistent with this app's
existing confidence-tagging discipline (`crawl_wallet_cluster`'s
"seed"/"co-spend"/"output" labels, `render_cluster_report`'s explicit
"discovery candidates, not certain findings" framing).

## 1. What Are We Doing?

Today, `find_overlap_addresses()` (shipped as `group-view-graph`) is the
only "related accounts" signal, and it's binary: an address counts as
related only if it was discovered by **more than one saved crawl run**,
with zero regard for *how strongly* connected it is. Meanwhile,
`crawl_wallet_cluster()`'s BFS actively **throws away** the exact
evidence needed for a real strength signal: `if co_spend not in
discovered: discovered[co_spend] = {...}` only records a link the FIRST
time an address is seen -- every other transaction that ALSO links two
already-known addresses (the literal "numerous transactions and
interactions" the user is asking for) is silently dropped, never
counted.

This adds real edge/interaction tracking (not just first-discovery),
persists it across every saved crawl run (not just the most recent one
in memory), and computes a transparent, weighted confidence score per
candidate address -- ranked, explained, never presented as certain.

## 2. What I Found

- `find_co_spend_addresses(tx, address)`/`find_output_addresses(tx,
  address)` (`tools/crawl_transaction_graph.py:46,59`) are called once
  per transaction per frontier address during the BFS
  (`crawl_wallet_cluster`, `:123-146`) -- the full transaction dict
  (including `tx["txid"]`, confirmed present on every real Blockstream
  API response and the test suite's `make_tx()` helper) is available at
  the exact point a co-spend/output relationship is discovered, but
  nothing beyond a single winner-take-first edge is kept.
- `web/crawl_runs.py`'s `run_addresses` table stores
  confidence/generation/balance per (run, address) -- no edge/
  relationship table exists at all. `find_overlap_addresses()`'s SQL
  (`GROUP BY address HAVING COUNT(DISTINCT run_id) > 1`) is the only
  existing cross-run signal, and it only sees the WINNING confidence tag
  per run, not transaction counts.
- `web/findings.py`'s `findings` table (coin, address, balance, ...) is
  this app's actual "known accounts" registry -- every address with a
  checked, real balance. This is the natural seed set for "related to
  our other accounts": known findings, not just whatever a single crawl
  happened to start from.
- No existing scoring/ranking anywhere in the codebase to build on or
  conflict with -- this is genuinely new capability, not a refactor.

## 3. My Proposed Approach

**Story csr-01 -- real edge tracking (backend, the data-correctness
foundation):** `crawl_wallet_cluster()` gains an `edges` list alongside
its existing `discovered` dict: every co-spend/output relationship
observed during the BFS -- **including repeat evidence for
already-discovered addresses**, deduplicated only by
`(from, to, type, txid)` so the SAME transaction is never double-counted
but genuinely DIFFERENT transactions between the same two addresses each
count. `web/crawl_runs.py` gains a `run_edges` table
(`run_id, from_address, to_address, edge_type, txid`) so this evidence
persists across every saved run, not just the one currently in memory --
score computation must be able to draw on the FULL history of everything
ever crawled, since "numerous transactions" only becomes visible in
aggregate over time.

**Story csr-02 -- confidence scoring + a real "Related accounts"
view (the actual suggestion the user asked for):** New
`compute_confidence_scores(known_addresses, db_path=...)` in
`web/crawl_runs.py`: for every discovered address that is NOT already a
known finding, aggregate its edges against the known-address set (direct
evidence) and against the rest of the discovered graph (broader
connectivity), weighted by evidence strength:

- direct co-spend transaction with a known address -- strongest single
  signal (common-input-ownership is near-certain proof of shared
  control)
- direct output transaction with a known address -- weaker (a real
  transfer, but transfers to third parties happen too)
- cross-run corroboration (also discovered by a separate, independent
  crawl) -- existing `find_overlap_addresses` signal, folded in
- each *additional distinct transaction* of an already-counted type adds
  incrementally, not linearly re-triggering the base signal -- five
  co-spend transactions with a known address is strong evidence, but
  it's evidence of the SAME underlying fact (common ownership), not five
  independent facts

Score is presented as a **breakdown, not a bare number** -- "3 co-spend
transactions with a known address, discovered via 2 separate crawls" --
so the reasoning is checkable, matching every existing confidence label
in this app. A coarse High/Medium/Low bucket derived from score
thresholds sits alongside the raw breakdown for a fast scan, but the
breakdown is always shown -- never a black-box number alone.

New `GET /findings/related` page (or extend `group_view.html` --
decided during implementation once the actual query shape is clear)
listing every scored candidate, ranked highest-confidence first, with
its full breakdown and a direct link into that address's own Graph view.

## 4. What This Does NOT Change

- `find_co_spend_addresses()`/`find_output_addresses()`/
  `fetch_address_transactions()` -- untouched, still the actual
  data-gathering logic.
- `discovered_via` (from `visual-transaction-graph`) -- untouched, still
  the one-edge-per-node tree used for the visual graph's layout. `edges`
  is an ADDITIVE, separate list -- the graph's ring layout still wants
  exactly one parent per node; scoring wants every piece of evidence.
  These are different consumers of the same underlying BFS with
  different needs, not a conflict.
- `find_overlap_addresses()` -- untouched, reused as one input signal to
  the new score, not replaced.
- Balance-checking, `findings.db` -- untouched; a scored candidate
  becomes a real finding only once its balance is actually checked, same
  as today.

## 5. Risks

- **This is the highest-stakes correctness surface in the app right
  now.** A wrong/inflated score reads as false hope. Mitigated by (a)
  never showing a bare score without its breakdown, (b) weighting
  co-spend far above output (co-spend is genuinely strong evidence;
  output is not), (c) explicit "candidate, not certain" language on the
  page itself, matching `render_cluster_report`'s existing framing.
- **Double-counting risk**: the same transaction observed from two
  different frontier addresses during BFS must not be counted twice --
  the `(from, to, type, txid)` dedup key is the safeguard, tested
  explicitly.
- **Performance**: persisting every edge (not just first-discovery)
  means more sqlite writes per crawl -- bounded by the existing
  `max_addresses=200` cap and typical transaction counts (Blockstream
  returns at most 25 recent txs per address per `fetch_address_transactions`),
  so this is at most a few thousand rows per crawl, not unbounded.

## 6. Scale Assessment

**Medium-large**, proportionate to how much this matters. Two stories:
edge tracking + persistence (csr-01), then scoring + the ranked view
(csr-02). Each ships and is verified independently, same discipline as
every other epic this session -- nothing about the stakes changes the
process, it raises the bar on care within it.
