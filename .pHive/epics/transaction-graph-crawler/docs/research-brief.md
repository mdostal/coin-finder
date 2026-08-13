# Research Brief: Blockchain Transaction-Graph Crawler

## Requirement

User request, prompted by the real 0.3 BTC find in `wallet-relationship-graph`/
`conservative-balance-retries` testing: "get a graph of these sorts of wallets --
the current accounts you have -- the tool needs to crawl a bit and do generations
each direction to see if there are sitting wallets where you got money from (I
mined a ton and then would transfer and know there are some sitting with 5+)."

## API confirmed live (Blockstream, same provider services/bitcoin.py already uses)

`GET https://blockstream.info/api/address/{address}/txs` returns up to 25 recent
confirmed transactions. Each has:
- `vin[].prevout.scriptpubkey_address` + `.value` (satoshis) — input addresses
- `vout[].scriptpubkey_address` + `.value` (satoshis) — output addresses
- `vin[].is_coinbase` — true for mining-reward transactions (directly relevant:
  user mentioned mining)

Verified against the real found address: 14 transactions, matches the "Confirmed
tx count 14" the user independently confirmed via a block explorer.

## Critical finding from the real transaction dump the user pasted

Several transactions on this one address have **100+ outputs** (one had what
looked like 300+). That pattern is a mining-pool payout or exchange batch
transaction, not a personal wallet-to-wallet transfer. A naive "follow every
address in every transaction" BFS crawl would explode into thousands of
unrelated addresses within 1-2 generations and hammer the API — both slow and
almost entirely noise (those other addresses belong to hundreds of unrelated pool
depositors, not the user).

## Technique: common-input-ownership heuristic (real, established blockchain-analysis practice)

When an address is used as one of several **inputs** on the same transaction, the
other input addresses on that transaction were necessarily signed by the same
wallet — building a transaction requires the private key for every input, so
co-spending is strong evidence of common ownership. This is the standard
technique used for address clustering without needing any private keys (all
inputs/outputs are public). It's the right primary signal here: cheap (bounded by
the seed address's own transaction count) and precise (doesn't fan out through
other people's addresses).

Output-following (where funds were *sent to*) is the "generations" direction the
user described (mined -> transferred -> maybe still sitting there), but is lower
confidence (an output can be a payment to someone else, not just the sender's own
change address) and must be bounded — skip transactions with an output count
above a cap, since high-fanout transactions are the mining-pool/exchange pattern
just confirmed, not a personal transfer.

## Cross-cutting concerns loaded

`documentation` only concern defined; applies (new tool needs README coverage).

## Confidence

High on the technique (well-established, and the fan-out risk was directly
observed in real data from this exact address, not theoretical). Medium on tuning
defaults (generation depth, output-count cap, balance-significance threshold) --
flagging as open questions for the design discussion rather than guessing.
