# Design Discussion: Exodus Wallet Unlock via hashcat

**Process note:** same no-live-teammates adaptation as prior epics. Required
real external research (a live web search) before any implementation
decision, similar to the earlier BTCRecover integration.

## 1. What Are We Doing?

A real Exodus desktop wallet was found on this machine
(`~/Library/Application Support/Exodus/exodus.wallet/seed.seco`). BTCRecover
does not support Exodus at all (confirmed: no `WalletExodus` class in
`btcrpass.py`). `seed.seco`'s own header, read live, identifies its scheme
explicitly: `"seco-v0-scrypt-aes"` (scrypt KDF + AES). Rather than
reimplementing that crypto by hand (real correctness risk for something
this high-stakes), research found that **hashcat's own official repository**
ships `tools/exodus2hashcat.py` -- a purpose-built extraction script (MIT
licensed) feeding hashcat's own mode 28200 ("Exodus Desktop Wallet
(scrypt)"), which is a first-class, natively supported hash mode, not a
community plugin.

## 2. What I Found (live research + live verification)

- `gurnec/btcrecover` and `3rdIteration/btcrecover` both lack Exodus support.
- `exodus2hashcat.py` (`hashcat/hashcat` repo, `tools/`) is real, current,
  and matches the real `seed.seco` header byte-for-byte (verified live:
  magic `SECO`, version tag `seco-v0-scrypt-aes`, `224`-byte header) -- ran
  it against the real file (safe: reads only public salt/KDF-parameter
  metadata, never a password) and got a correctly-shaped `EXODUS:...` hash
  line.
- hashcat mode 28200 is confirmed installed and working (`hashcat
  --example-hashes` shows it as first-class, non-deprecated, self-test
  enabled) -- **and ships its own official example hash + password**
  (`Example.Pass: hashcat`), the same class of public test fixture as the
  BIP39 test vector and BTCRecover's bundled test wallet used elsewhere in
  this project.
- A hand-constructed synthetic test hash (built from the `METADATA_*` size
  constants in `exodus2hashcat.py`) was tried first and was **wrong** --
  the real format has a two-layer key-wrapping structure more intricate
  than the constants alone reveal, and hashcat rejected it with a "Token
  length exception." Abandoned in favor of hashcat's own shipped example,
  which is correct by construction and requires no hand-replication of the
  format.
- Running the real crack (even against the tiny example) initially failed
  with a device-memory allocation error -- scrypt is intentionally
  memory-hard, and this sandboxed environment's memory reporting confused
  hashcat's default allocation. Fixed with `--backend-devices-keepfree 5
  --scrypt-tmto 4`, which trades some speed for reliability and is now a
  default flag in this project's wrapper (a real environment finding, not
  just a one-off workaround -- the user could hit the same thing on their
  own machine, especially on Apple Silicon unified-memory systems).

## 3. Approach

1. `scripts/install_exodus_tools.sh`: fetches `exodus2hashcat.py` from
   hashcat's official repo into `vendor/hashcat-tools/` (not committed,
   same treatment as `vendor/btcrecover/`) and installs hashcat itself via
   Homebrew on macOS (with a manual-install note for other platforms).
2. `tools/unlock_exodus_wallet.py`:
   - `extract_exodus_hash(seed_seco_path)` -- shells out to
     `exodus2hashcat.py`, returns the hash line. Safe (public metadata
     only).
   - `run_exodus_unlock(seed_seco_path, candidates_file, allow_online=False)`
     -- **same hard offline safety gate as `unlock_wallet.py`**, reusing
     `check_network_status()` from that module rather than duplicating it.
     Extracts the hash, writes it to a temp file, runs `hashcat -m 28200
     -a 0 --potfile-disable --backend-devices-keepfree 5 --scrypt-tmto 4
     -o <outfile> <hashfile> <candidates_file>`.
   - CLI: candidates from a file only, never a CLI argument (same
     established rule).

## 4. What Could Go Wrong

- **critical** (handling, not detection) -- same class of risk as the
  BTCRecover integration: running a real password attempt against a real
  wallet while online. Mitigated identically -- hard offline gate, and this
  epic's own testing never touches the real `seed.seco`, only hashcat's own
  public example.
- **medium** -- `--backend-devices-keepfree`/`--scrypt-tmto` tuning was
  needed in this specific sandboxed environment; the user's own machine may
  or may not need it, but the flags are harmless (just a speed/reliability
  tradeoff) when not strictly necessary, so they're kept as defaults rather
  than conditionally applied.
- **low** -- `vendor/hashcat-tools/exodus2hashcat.py` and hashcat itself
  track upstream, not pinned in this repo's history -- same accepted
  tradeoff as `vendor/btcrecover/`.

## 5. Verification Strategy

```
VERIFICATION PLAN:
  Tools: pytest, plus hashcat itself and its own official example hash
  Automated: offline safety-gate tests (mocked network status);
    extract_exodus_hash()'s error handling on a malformed file (real script,
    real subprocess, no real seed.seco needed); a REAL hashcat crack against
    hashcat's own official example hash + password (mode 28200,
    "Example.Pass: hashcat") -- genuinely exercises the full crack mechanism
    this tool's CLI drives, without touching any real wallet
  Manual: extraction against the REAL seed.seco was validated live during
    research (safe -- public metadata only); the actual password-guessing
    run against the real wallet is the user's to run themselves, offline,
    same principle as the BTCRecover integration
  Not verifying: cracking the user's actual Exodus wallet in this session
```

## 6. Scale Assessment

```
SCALE ASSESSMENT:
  Files affected: ~4 (new scripts/install_exodus_tools.sh, new
    tools/unlock_exodus_wallet.py, new tests/test_unlock_exodus_wallet.py,
    README.md edit) + vendored exodus2hashcat.py
  RECOMMENDATION: Proceed to a single story
```
