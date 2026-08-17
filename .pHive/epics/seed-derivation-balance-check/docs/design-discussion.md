# Design Discussion: Seed-Phrase HD Derivation + Balance Check

**Process note:** same no-live-teammates adaptation as prior epics.

## 1. What Are We Doing?

Given a candidate seed phrase (from `find_seed_phrases.py`'s output), derive
real addresses across several known wallet-derivation schemes and check each
for a balance -- "try them on accounts." User explicitly scoped v1 as
"bounded but as many schemes as possible," with a more exhaustive "deep dive"
mode explicitly deferred to a future epic (their words: "we should plan for
and get an epic together to have an advanced menu... people can re-run just
that against the leftovers").

## 2. Approach

1. **New dependency**: `bip_utils` (added to `requirements.txt`) -- actively
   maintained, widely used, covers BIP32/39/44/49/84 and many coins. Reusing
   an audited implementation for the actual EC math, per the established
   "audited library for anything touching key material" agreement. Verified
   live against the standard public BIP39 test vector -- all derived
   addresses matched the well-known, publicly documented test vectors for
   that mnemonic.
2. **`tools/match_seed_phrases.py`**:
   - `derive_candidate_addresses(phrase, num_addresses=5)` -- for each scheme
     in a bounded set (BIP44/BIP49/BIP84 for Bitcoin, BIP44 for Ethereum and
     Litecoin -- the coins with existing balance-check services), derive the
     first `num_addresses` external-chain addresses (`account=0, change=0,
     index=0..N-1`). Returns `[{"scheme": str, "coin": str, "index": int,
     "address": str}, ...]`. **Never computes or exposes a raw private key /
     WIF** -- only public addresses. If a match is found, the user re-derives
     the actual spending key themselves in trusted wallet software, now
     knowing which phrase/scheme/index worked.
   - `check_derived_balances(derived)` -- reuses existing per-coin services
     (`BitcoinService`, `EthereumService`, `LitecoinService`) and the retry
     helper already built in `check_wallet_balances.py`
     (`_check_balance_with_retries`) -- no duplicated balance-check logic.
   - `render_match_report(...)` -- phrase text appears in the report only for
     phrases that produced at least one non-zero-balance address (the actual
     finding); phrases with nothing found are reported by input index only,
     not by phrase text, to avoid gratuitously repeating secret material for
     no benefit.
3. **CLI reads phrases from a file only, never a command-line argument** --
   CLI args are visible in shell history and `ps aux`; a real exposure risk
   for something that IS private-key material. Accepts either
   `find_seed_phrases.py`'s output JSON directly (flattens to a unique phrase
   list) or a plain newline-separated phrase file.
4. **Same stdout rule as `find_seed_phrases.py`**: never print phrase text to
   console, only counts/addresses/balances (addresses and balances are public
   blockchain data, safe to display; the phrase is the only secret here).

## 3. What Could Go Wrong

- **medium** -- Bounded scheme coverage (BIP44/49/84 x BTC/ETH/LTC, 5
  addresses each) will miss genuinely exotic old wallets (original pre-BIP32
  Bitcoin Core HD, Electrum 1.x's nonstandard scheme). Explicitly deferred to
  the user-requested "deep dive" follow-up epic, not silently dropped --
  stated in the report's summary line.
- **medium** -- API load: ~30-45 addresses checked per phrase (3 BTC schemes
  x 5 + 2 more coins x 5), each with up to 3 retries. For a handful of
  candidate phrases this is fine; for many phrases this could take a while.
  Accepting this for v1 (matches "thoroughness over speed" from the
  north-star); the deep-dive epic is the natural place to add
  parallelization/rate-limit-aware batching if it becomes a real bottleneck.
- **high** (handling, not detection) -- Same class of risk as
  `find_seed_phrases.py`: careless phrase-text handling. Same mitigations
  (file-only input, no-stdout-printing, phrase text only in the report when
  there's an actual finding).

## 4. Verification Strategy

```
VERIFICATION PLAN:
  Tools: pytest
  Automated: derive_candidate_addresses() against the standard public BIP39
    test vector (verified live -- matches publicly documented test-vector
    addresses for BIP44/49/84 BTC and BIP44 ETH); check_derived_balances()
    with mocked services (no real network calls in the test suite);
    render_match_report() phrase-redaction behavior; CLI stdout-safety test
  Manual: run the CLI against the test vector to sanity-check real balance
    lookups resolve (the test vector's addresses are long-known to be empty,
    so this validates plumbing without needing a funded real phrase)
  Not verifying: coins/schemes outside the bounded v1 set (explicitly
    deferred to the deep-dive follow-up epic)
```

## 5. Scale Assessment

```
SCALE ASSESSMENT:
  Files affected: ~3 (new tools/match_seed_phrases.py, new
    tests/test_match_seed_phrases.py, requirements.txt + README.md edits)
  RECOMMENDATION: Proceed to a single story
```
