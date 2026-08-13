# Design Discussion: Fork Coin Checker + BitcoinGoldService Fix

**Process note:** same no-live-teammates adaptation as prior epics.

## 1. What Are We Doing?

User request: check whether found Bitcoin addresses also hold balances on
coins that forked from Bitcoin at the same address/keys (Bitcoin Cash,
Bitcoin Gold) -- "maybe we get some btc gold or something worth a couple
bucks." A hard fork copies the entire ledger, so any address that held BTC
at the fork snapshot controls the identical balance on the forked chain too,
under the same private key. No new derivation needed -- just additional
balance checks against the same address.

## 2. What I Found (a real, pre-existing bug)

While building this, `services/bitcoin_gold.py::check_balance()` was found
pointing at `https://blockchair.com/bitcoin-gold/address/{address}` -- the
**webpage** URL, not `https://api.blockchair.com/bitcoin-gold/dashboards/
address/{address}`, the **API** URL that `services/bitcoin_cash.py` (correct)
already uses. This means every Bitcoin Gold balance check in this project's
history has silently returned `None` (fetching HTML, `.json()` parsing
fails, caught by the broad `except`) -- indistinguishable from "no balance"
without looking at the code. Fixed to match `bitcoin_cash.py`'s working
pattern. First test coverage for any `services/*.py` file in this repo.

## 3. Approach

1. Fix `services/bitcoin_gold.py`'s URL + response parsing (one-line class of
   fix, mirrors the already-correct `bitcoin_cash.py`).
2. `tools/check_fork_coins.py`: `FORK_COINS = ["Bitcoin Cash", "Bitcoin
   Gold"]` -- coins with an existing service in this project that share
   Bitcoin's address format. Bitcoin SV (BSV) shares the format too but has
   no service here; stated as a known gap in the report, not silently
   omitted.
   - `check_fork_coin_balances(address, coins=None)` -- reuses
     `check_wallet_balances.py`'s `load_service()` and
     `_check_balance_with_retries()` (no duplicated logic).
   - `check_fork_coins_for_addresses(addresses, coins=None)` -- batch.
   - `load_addresses_from_file(path)` -- tolerant loader accepting
     `scan_wallet_dat.py`'s output shape, `crawl_transaction_graph.py`'s
     output shape, or a plain newline list, so this tool composes directly
     with the pipeline's other outputs.
   - `render_fork_coin_report()` -- calls out any non-zero balance.

## 4. What Could Go Wrong

- **low** -- Blockchair (used by both Bitcoin Cash and Bitcoin Gold
  services) rate-limited this session's IP during research (`430` response,
  confirmed live) after a day of heavy testing. Not a code bug -- the
  existing retry-and-report-inconclusive behavior already handles this
  correctly (never coerces a rate-limited/failed check to "confirmed zero").
  Live verification of the fix was done via mocked tests as the primary
  check, consistent with established project practice.
- **low** -- Bitcoin SV isn't covered (no service exists). Stated in the
  report text, not a silent gap.

## 5. Verification Strategy

```
VERIFICATION PLAN:
  Tools: pytest
  Automated: services/bitcoin_gold.py's URL/parsing fix (new
    tests/test_services_bitcoin_gold.py -- first test coverage for any
    services/*.py file); check_fork_coins.py's core functions, all with
    mocked services (no real network calls, given the live rate-limit
    encountered during research)
  Manual: none against real network this session, given the confirmed
    Blockchair rate-limit -- mocked tests are the verification of record
  Not verifying: Bitcoin SV (no service exists, stated gap)
```

## 6. Scale Assessment

```
SCALE ASSESSMENT:
  Files affected: 4 (services/bitcoin_gold.py fix, new
    tests/test_services_bitcoin_gold.py, new tools/check_fork_coins.py, new
    tests/test_check_fork_coins.py) + README.md
  RECOMMENDATION: Proceed to a single story
```
