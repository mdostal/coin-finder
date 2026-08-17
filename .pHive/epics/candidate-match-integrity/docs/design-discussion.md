# Design Discussion: Candidate Match Integrity

## 1. What Are We Doing?

`config/analysis.py`'s `CRYPTO_PATTERNS` regexes are pure shape matches --
no coin-specific checksum or structural verification -- so garbage text
that merely *looks* like an address gets extracted, balance-checked, and
in some cases permanently stored as a "finding." Tonight's real report: a
prior scan's own output file (`.../helium/checks/wallet_analysis.json`)
was re-scanned as if it were wallet content, and Rust mangled-symbol
strings inside it (`d6thread6Thread5cname17hd86fb86E`,
`df29a6dde7b3e33ab57f416f11`) matched the `Digibyte` pattern and were
recorded as candidate addresses with a 0.0 balance. User's words: *"you
can see an overfit of the regex where it is trying the wrong thing for
addresses AND these addresses are in a helium folder, so they are helium
HNT... and it needs to be fixed, not scanning random bad matches like are
happening."*

Goal: stop shape-only noise from becoming stored findings or burning
balance-check API calls, for every coin where that's actually possible
without a network call -- and be straight about the coins where it isn't.

## 2. What I Found

**The pattern table** (`config/analysis.py:1-22`) is accurate as given in
the brief -- 19 entries, no checksum/validity logic anywhere in the file,
just `re` alternations. `OKCash`'s `r"[0-9A-Za-z]{34}"` is the extreme
case: no coin-specific structure at all, and it even includes `0`, `O`,
`I`, `l` -- characters base58 alphabets deliberately exclude, so it isn't
even shape-tight for what OKCash's real (base58-derived) addresses look
like.

**Where a match becomes a stored candidate.** `CRYPTO_PATTERNS` has
exactly two consumers:
- `tools/analyze_wallets.py:22-25` -- `analyze_wallet_file()` reads a
  file's full bytes, runs every pattern via `re.findall`, and returns
  `{coin: [matches...]}` with zero filtering. This is **the** site: its
  output (`analyze_wallets()`, `tools/analyze_wallets.py:30-87`) is
  written straight to `wallet_analysis.json` by `run_pipeline.find()`
  (`run_pipeline.py:68-76`) -- this is the exact file from tonight's
  report.
- `tools/scan_gmail.py:210-224` -- `find_addresses_in_payload()`, the same
  blind loop against Gmail message bodies. A second, independent path
  that needs the same fix or the bug just reappears there.

**Where a candidate becomes an API call.**
`tools/check_wallet_balances.py:164-170` builds one `(file_path, address)`
task per address per coin straight from `wallet_analysis.json`, no
filtering; `check_one()` (`check_wallet_balances.py:206-219`) calls
`service.check_balance(address)` unconditionally. I read three services
end to end (`services/bitcoin.py`, `services/digibyte.py`,
`services/okcash.py`) -- all three build a URL from the address string and
`requests.get()` it with no validation at all, confirming the pattern
holds project-wide, not just for the coin in tonight's report.

**Where a candidate becomes a permanent "finding."**
`web/app.py:1683-1689` and `web/app.py:1726-1731` iterate
`wallet_balances.json` and call `record_finding(coin, address, balance,
...)` (`web/findings.py:52`) for **every** address, **regardless of
balance, including 0.0** -- this is the exact mechanism tonight's garbage
Digibyte "finding" came from.

**A validity primitive already exists in this codebase's own
dependencies -- no new dependency needed.** `bip_utils` is already in
`requirements.txt` (used by `tools/match_seed_phrases.py`,
`tools/extract_private_key.py`, `tools/scan_wallet_dat.py`) and ships
`Base58Decoder.CheckDecode()`, a generic base58check-with-checksum
decoder. I ran it directly: a real Bitcoin address decodes cleanly; one of
tonight's actual mangled strings
(`d6thread6Thread5cname17hd86fb86E`) raises
`Base58ChecksumError: Invalid checksum` immediately. `bip_utils` also
ships purpose-built decoders for Ripple's own alphabet
(`Base58Alphabets.RIPPLE`), Monero's own checksum scheme
(`XmrAddrDecoder`), Bitcoin Cash's cashaddr checksum
(`BchP2PKHAddrDecoder`/`BchP2SHAddrDecoder`), and even Cardano
(`AdaShelleyAddrDecoder`, `AdaByronAddrDecoder`) and Cosmos
(`AtomAddrDecoder`) -- all confirmed present by inspecting the installed
package, not assumed.

**Existing test coverage to preserve:** `tests/test_analyze_wallets.py`
(6 tests) is the only file exercising this path directly (grepped
`tests/` for `CRYPTO_PATTERNS`/`analyze_wallet_file` -- nothing else hits
it). It already uses a real, checksum-valid Bitcoin address
(`1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2`) as its fixture, which is good news:
a correct validity filter should leave every one of those 6 tests passing
unchanged. `tests/` collects 657 tests total today; none of the others
touch `CRYPTO_PATTERNS`.

**A secondary, pre-existing gap, noted but out of scope:**
`config/wallet.py`'s `WALLET_SERVICES` lists 21 coins (includes Bitcoin SV
and Feathercoin), but `CRYPTO_PATTERNS` only has 19 -- those two coins
have a working balance-check service but can never be found by the regex
scan today. Real, but unrelated to tonight's bug (a missing-match problem,
not a false-match problem) -- flagging for a separate follow-up, not
folding it in here.

## 3. My Proposed Approach

**Add offline validity filtering at the match site, for every coin where
a real, verifiable-without-a-network-call checksum exists.** Concretely: a
new small module (e.g. `config/address_validators.py`) mapping each
`CRYPTO_PATTERNS` key to a `validate(address) -> bool` built on `bip_utils`
primitives already installed. `tools/analyze_wallets.py:22-25` and
`tools/scan_gmail.py:220-224` both filter `re.findall()`'s output through
it before returning -- one shared module, both call sites, so the fix
doesn't silently miss the Gmail path. This is the earliest possible point
in the pipeline: garbage never reaches `wallet_analysis.json`, never
burns a balance-check API call, and never reaches `record_finding()`.
Filtering later (e.g. only at `record_finding()` time) would still let
garbage waste real API calls against public services -- worth avoiding
even though those are rate-limited already.

**Honest three-way split of the 19 coins**, because a checksum filter
that doesn't exist for a coin isn't a fix I should promise:

- **Real checksum, verifiable offline, tooling already installed** --
  Bitcoin, Bitcoin Gold, Digibyte, Diamond Coin, Litecoin, Dogecoin,
  Zcash, Tether's base58 (Omni) branch (all standard base58check, Bitcoin
  alphabet, via `Base58Decoder.CheckDecode`), Ripple (own base58
  alphabet, `Base58Alphabets.RIPPLE`), Monero (`XmrAddrDecoder`), Bitcoin
  Cash (cashaddr, `BchP2PKHAddrDecoder`/`BchP2SHAddrDecoder`), Cardano
  (`AdaShelleyAddrDecoder`/`AdaByronAddrDecoder`), Cosmos
  (`AtomAddrDecoder`), and Helium (publicly documented as base58check;
  I couldn't pin its exact version byte from public docs, but generic
  `Base58Decoder.CheckDecode` still validates checksum correctness
  without needing that byte -- it only requires the string decode and
  checksum verify, which a random match essentially never does by
  chance). This is the coin named directly in tonight's report and the
  first one worth a real fixture-backed test.
- **Real checksum exists at the protocol level, but the tooling gap is
  real** -- Binance Coin (BNB Beacon Chain addresses are bech32,
  checksummed, but `bip_utils` has no `BnbAddr*` decoder; closing this
  needs either a new small `bech32` dependency or a hand-rolled bech32
  checksum). Feasible, but a discrete follow-up rather than folded into
  this fix -- adding a new dependency is a bigger decision than reusing
  one already vetted and installed.
- **No meaningfully offline-verifiable structure** -- Ethereum, Ethereum
  Classic, Shiba Inu (`0x` + 40 hex): EIP-55 mixed-case checksumming
  exists but is *optional*, and real addresses seen in the wild are
  routinely all-lowercase with no checksum encoded -- enforcing it would
  reject genuine unchecksummed addresses, a false-negative regression,
  not a fix. The regex is already about as tight as the shape allows (an
  exact 20-byte hex string is real structure, unlike OKCash below); IOTA
  (`[A-Z9]{81}`): the real IOTA checksum is a separate 9-tryte suffix
  the current regex doesn't even capture, and trytes aren't a `bip_utils`
  or any other already-installed alphabet -- closing this needs new,
  hand-written checksum logic, flagged as a follow-up rather than
  attempted here; OKCash (`[0-9A-Za-z]{34}`): no per-coin structure
  today at all. Realistic fix here is two-tiered and both parts are
  cheap: (a) tighten the regex to an actual base58 alphabet (drop `0`,
  `O`, `I`, `l`), and (b) apply the same generic
  `Base58Decoder.CheckDecode` checksum filter used for the Group 1 coins
  above -- it doesn't require knowing OKCash's exact version byte, only
  that the string round-trips as valid base58check, which is still a
  large, real improvement over today's zero-structure regex.

**The scan-exclude question -- recommend against a built-in path
heuristic.** I read `web/scan_excludes.py:25-35` closely: its own
docstring is explicit that this project deliberately keeps excludes
**user-configurable, never a built-in blocklist** -- *"What's worth
excluding... is something only the user actually knows, not something
this project should guess at."* Baking in a pattern like
`**/output/**/checks/*.json` would cut directly against that established
stance, and it's also the narrower fix: it only suppresses this one
false-positive *source* (re-scanning prior output), not the underlying
problem (an unvalidated match is wrong wherever it's found -- a Rust
binary anywhere on disk would trigger the same bug). Validity filtering
fixes the actual defect everywhere; a directory exclude would just hide
one instance of it. Users who want to skip their own output directories
already can, today, via the existing user-configurable excludes UI
(`web/app.py:801-811`) -- no code change needed for that.

## 4. Risks

- **False negatives are the real danger, not false positives.** A
  filter that's too strict would silently make a genuine Digibyte/
  Bitcoin/etc. address stop being found -- arguably worse than tonight's
  bug for a tool whose entire purpose is not missing a real wallet. Every
  Group 1 validator needs a test fixture built from a real, valid address
  for that coin (most already used as literal examples in this
  investigation, e.g. the existing Bitcoin fixture), not just a
  synthetic string.
- **Two independent call sites** (`tools/analyze_wallets.py` and
  `tools/scan_gmail.py`) must both route through the same shared
  validator module -- fixing only the first (the one in tonight's report)
  would leave the Gmail scan path exploitable by the identical bug.
- **`tests/test_analyze_wallets.py`'s dedup-cache tests** patch
  `analyze_wallet_file` directly and feed a fabricated
  `{"Bitcoin": ["1cached"]}` result through `scan_index`'s cache
  short-circuit -- that path never calls the real regex/validator logic,
  so it's unaffected either way, but worth calling out explicitly so a
  future reader doesn't mistake `"1cached"` for something that needs to
  pass real validation.
- **Don't overclaim coverage.** Group 3's coins (Ethereum family, IOTA,
  OKCash's exact version byte) need the design's honesty to survive into
  the story writeup and the shipped changelog -- this is a partial fix by
  design, not "all false positives eliminated."
- **`bip_utils` is currently unpinned** in `requirements.txt` (bare
  `bip_utils`, no version) -- worth pinning as part of this work now that
  correctness (not just encoding) depends on its decoder behavior,
  independent of whether that's this epic's job or a one-line drive-by.

## 5. Scale Assessment

**Small-to-Medium.** Contained to a handful of files: one new validators
module, two existing call sites gain a filter step
(`tools/analyze_wallets.py`, `tools/scan_gmail.py`), `config/analysis.py`
gets OKCash's regex tightened, plus new tests per coin group (real-address
fixtures for the ~14 Group 1 coins, explicit "still passes through
unchanged" tests for Group 3). No `services/*.py` changes needed --
filtering happens upstream of every service, so none of the 21 balance
-check services are touched. No UI/template changes, no new persistent
storage, no new dependency (Group 1 + OKCash's tightening ship entirely on
`bip_utils`, already installed). Multi-file but well-understood and
low-risk if the false-negative fixtures are done properly -- not a
redesign, and not touching the scan-exclude system at all per the
recommendation above.
