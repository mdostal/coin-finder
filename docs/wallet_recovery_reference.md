# Wallet & Service Recoverability Reference

This is a **reference for you to cross-check against your own memory** -- not
an automated classifier. Reliably detecting "this specific address belonged
to exchange X" from blockchain data alone isn't something this project can do
confidently (that requires proprietary address-attribution databases that big
blockchain forensics companies maintain, not something buildable from public
chain data). What this project's tools *can* tell you (via
`crawl_transaction_graph.py`'s dormancy check and co-spend clustering) is
*when* an address was last active and *which other addresses* likely belong
to the same wallet -- use that alongside your own memory of what
service/software you actually used, and this doc, to judge realistic
recovery odds.

## Self-custody wallet software found on disk (this project's tools identify these directly)

| Software | Status | Recovery path |
|---|---|---|
| **Bitcoin Core** (`wallet.dat`) | Actively maintained | If unencrypted: keys are directly recoverable (see `scan_wallet_dat.py`). If encrypted: password recovery via `unlock_wallet.py` (BTCRecover). |
| **Electrum** | Actively maintained | Seed-phrase or password recovery via BTCRecover (`seedrecover.py` for the seed, `btcrecover.py` for the wallet-file password). This project's `find_seed_phrases.py` / `match_seed_phrases.py` also help if you have (or can find) the seed. |
| **Armory** | No longer actively developed, but wallet format is well-documented and BTCRecover explicitly supports it. Historically required a full node to spend from — check whether that's still true for your version before assuming you need to run one. | Password recovery via BTCRecover (`--wallet-type armory` variants). Worth checking `vendor/btcrecover/docs/` after install for Armory-specific notes. |
| **Multibit, bitcoinj-based wallets, Bither, mSIGNA, Blockchain.info wallet exports** | Varies -- some discontinued, some still installable | BTCRecover supports password recovery for all of these directly, per its own README's feature list. |

## If it turns out to be an exchange/custodial service, not a self-custody wallet

If an address's activity pattern or your own memory suggests funds went to
(or came from) an **exchange or custodial web wallet** rather than a wallet
file you controlled, the recovery path is fundamentally different -- no
password or seed phrase will help, because you never held the keys. What
matters is whether that specific company still exists, was acquired, or went
through a bankruptcy process with a claims window:

- **Mt. Gox** -- collapsed 2014. A bankruptcy claims/rehabilitation process
  has been distributing recovered funds to verified creditors for years; if
  you had an account there, check for official rehabilitation-plan
  correspondence (not third-party "recovery services," which are commonly
  scams targeting former Mt. Gox users specifically).
- **MyBitcoin** -- an early (2011) custodial wallet service that lost
  customer funds; no formal recovery process exists.
- **Bitcoinica, Bitomat, Instawallet** -- other early (2011-2012) custodial
  services that shut down or lost funds; generally no recovery path exists
  for these today.
- **Mining pool payout wallets** (e.g. old BTC Guild, Deepbit, Slush Pool/
  Braiins-era accounts) -- some pools kept custodial balances rather than
  paying out directly to a wallet you controlled. If a pool is still
  operating (Braiins Pool, the Slush Pool successor, is), check whether they
  retain historical account records. If a pool shut down entirely, recovery
  depends entirely on whether it ever formally wound down with a claims
  process (most early pools did not).

**General rule of thumb:** if the funds ever touched a service that required
you to log in with a username/password (not a wallet file/seed phrase you
controlled), that's custodial, and the technical tools in this project (which
only ever work with keys/seeds/wallet files you actually possess) can't help
recover it directly -- the path is contacting that company (if it still
exists) or checking for a bankruptcy claims process (if it doesn't).

**Be wary of "wallet recovery services" that ask you to send funds or private
keys upfront** -- this space attracts scams specifically targeting people
searching for exactly what you're doing right now.

## What this project's own tools can tell you, to help you decide

- `crawl_transaction_graph.py`'s dormancy output tells you exactly when an
  address was last active -- if it's been dormant since, say, 2013 and you
  recall using an exchange around then, that's a real data point pointing at
  "custodial, not self-custody."
- Co-spend clustering can trace an address back to others that were spent
  from the same wallet -- if that cluster eventually connects to an address
  you recognize as one you personally held keys for (vs. one you only ever
  saw as a balance on a website), that distinguishes self-custody from
  custodial.
