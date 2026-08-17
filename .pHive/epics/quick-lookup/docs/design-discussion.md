# Design Discussion: Quick Single-Address Balance Lookup

**Process note:** same no-live-teammates adaptation as every epic this
session. Requested directly: "I may be able to just say -- this is an
okcoin, just get me the balance."

## 1. What Are We Doing?

A fast path that skips the whole search/analyze pipeline: paste an
address, pick the coin, get the balance. No directory scan, no file
discovery -- for when you already know an address (from a Group View
overlap, a note, memory) and just want its balance checked.

## 2. What I Found

Everything needed already exists in `tools/check_wallet_balances.py`:
- `load_service(crypto_name)` -- dynamically resolves the right
  `WalletService` subclass from `config/wallet.py`'s `WALLET_SERVICES` map.
- `_check_balance_with_retries(service, address)` -- retries on the
  existing "couldn't confirm" (`None`) signal, returns immediately on a
  real result including `0.0`.

This is a UI + thin orchestration feature, not new balance-check logic --
literally the same two calls `check_wallet_balances()` already makes per
address, just for one address instead of a whole file's worth.

## 3. My Proposed Approach

**New route `GET /lookup`** (`web/templates/lookup.html`): address input +
coin `<select>` populated from `WALLET_SERVICES.keys()` (Bitcoin default,
alphabetical otherwise -- matches this project's only existing coin list,
no new data).

**New route `POST /lookup`**: starts a background job (real network call
with retries -- same job pattern as every other network-touching action
this app has). `_run_quick_lookup_job(coin, address)`:
```python
service = load_service(coin)
balance = _check_balance_with_retries(service, address)
record_finding(coin, address, balance, source_label="quick_lookup")
return {"report": f"{address} ({coin}): {balance_str}"}
```
Reuses `item_result.html`'s existing generic `job.result.report` rendering
-- no new results template needed.

**No auto-detection of coin from address format.** `CRYPTO_PATTERNS` regex
are loose by design (built for casting a wide net across file content, not
validating a single known-good address) -- the exact false-positive
pattern already documented for OKCash/DigiByte/Ripple. An explicit dropdown
is simpler and can't silently guess wrong.

## 4. Scale Assessment

**Small.** 1 new template, ~15 lines in `web/app.py` (route + job
function, both trivial orchestration of existing functions). One story.
