
# Cryptocurrency Wallet Pipeline

---

## Overview

This project is a modular pipeline designed to **discover cryptocurrency wallet files**, **analyze them for wallet addresses**, and **check balances for supported cryptocurrencies**. It supports a growing list of cryptocurrencies and is designed for extensibility, allowing easy integration of new coins and processes.

---

## Why?

If anyone is like me and happens to stash crypto coins like a squirrel stashes nuts... often forgetting where they are.... I've created a toolset to help find wallets, check them for coins, and filter the files down to reasonable ones based on what it found on the corresponding blockchain,

The wallet tools I found out there just didn't match up to what I needed them to do and the ones that did often pulled in a number of 3rd party libs that I'd want to check to see if they were trojans (or they straight up had no source code and just an executable that I'm certain was malware).

So, here's a thing!

If you like it and want to support me making community tools, here are some options:

- Star the repo
- Tweet about it

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/mdostal)

Feel free to reach out if you have any questions or suggestions! (Or if you'd like to see this as a single downloadable executable)

## File Structure

```plaintext
project/
├── config/                   # Configuration files for search, analysis, and wallet services
│   ├── search.py      # Config for file extensions and keywords to find wallet files
│   ├── analyze.py     # Regex patterns for detecting wallet addresses
│   ├── wallet.py      # Maps cryptocurrencies to their respective service modules
├── services/                 # Individual wallet services for each cryptocurrency
│   ├── __init__.py           # Base WalletService class
│   ├── bitcoin.py            # Bitcoin wallet service
│   ├── ethereum.py           # Ethereum wallet service
│   ├── ripple.py             # Ripple wallet service
│   ├── ... (other services)  # Add additional wallet services here
├── tools/                     # Tools for pipeline stages
│   ├── search_wallets.py     # Finds potential wallet files
│   ├── analyze_wallets.py    # Analyzes files for wallet addresses
│   ├── check_wallet_balances.py  # Checks balances for wallet addresses
│   ├── filter_wallets.py     # Filters out zero-balance wallets
│   ├── build_wallet_graph.py # Correlates wallets/coins across files into a relationship report
│   ├── detect_hidden_volumes.py # Standalone: flags likely encrypted-container files (detect/flag only)
│   ├── crawl_transaction_graph.py # Standalone: discovers likely same-owner Bitcoin addresses via public tx graph
│   ├── find_seed_phrases.py  # Standalone: scans text files for checksum-valid BIP39 seed phrases
│   ├── match_seed_phrases.py # Standalone: derives addresses from seed phrases (bounded schemes) and checks balances
│   ├── unlock_wallet.py      # Standalone: offline-gated wrapper around BTCRecover for wallet password testing
│   ├── scan_wallet_dat.py    # Standalone: enumerates every address in a wallet.dat (not just text-matchable ones)
│   ├── check_fork_coins.py   # Standalone: checks found Bitcoin addresses on fork coins (Bitcoin Cash, Bitcoin Gold)
│   ├── unlock_exodus_wallet.py # Standalone: offline-gated wrapper around hashcat for Exodus wallet password testing
│   ├── scan_google_drive.py  # Standalone: slow-crawls Google Drive for wallet-like files, downloads to local disk
├── scripts/
│   ├── install_btcrecover.sh # Clones/updates BTCRecover into vendor/btcrecover/ (not committed)
│   ├── install_exodus_tools.sh # Installs hashcat + fetches exodus2hashcat.py into vendor/hashcat-tools/ (not committed)
├── .env.sample               # Sample env file for API keys (not committed with real values)
├── requirements.txt          # Python dependencies
├── run_pipeline.py           # Orchestrates the entire pipeline
---
```

## Tools

### **1. Search Tool (`search_wallets.py`)**
- **Purpose**: Searches for files that may contain cryptocurrency wallets.
- **How it works**:
  - Uses predefined extensions and keywords from `config/search_config.py`.
  - Recursively scans a directory and outputs a list of potential wallet files.
- **Usage**:
  ```bash
  python tool/search_wallets.py <start_path> <output_file>
  ```
**Example**:
  ```bash
  python tool/search_wallets.py ./wallets ./output/wallet_search_output.txt
  ```

--- 


### 2. Analyze Tool (`analyze_wallets.py`)

- **Purpose**: Analyzes the identified files for cryptocurrency wallet addresses.
- **How it works**:
  - Uses regex patterns defined in `config/analyze_config.py` to detect wallet addresses.
  - Processes files line by line or as binary data to extract addresses.
- **Usage**:
```bash
  python tool/analyze_wallets.py <input_file> <output_file>
```

**Example**:
```bash
  python tool/analyze_wallets.py ./output/wallet_search_output.txt ./output/wallet_analysis.json
```

---

### 3. Wallet Checker Tool (`check_wallet_balances.py`)

- **Purpose**: Checks balances for wallet addresses extracted during analysis.
- **How it works**:
- Dynamically loads services for each cryptocurrency based on `config/wallet_config.py`.
- Fetches balances using APIs or node integrations for each coin.
- Supports filtering coins via the `--coins` argument.
- Retries a failed/inconclusive check (API error, timeout, rate limit) up to 3 times with a 2-second backoff before giving up on an address -- a confirmed balance, including `0.0`, is never retried. Addresses still inconclusive after all retries are written to `inconclusive_balances.json` instead of silently being treated as empty (see Failsafes below).
- **Usage**:

```bash
python tool/check_wallet_balances.py <input_file> <output_file> [--coins <coin1> <coin2> ...]
```

**Example**:
```bash
python tool/analyze_wallets.py ./output/wallet_search_output.txt ./output/wallet_analysis.json
```

### 4. Relationship Graph Tool (`build_wallet_graph.py`)

- **Purpose**: Correlates wallet data across files and coins to surface relationships the other stages can't see on their own.
- **How it works**:
  - Reads `wallet_balances.json` (or `wallet_analysis.json`) and builds a graph of files, addresses, and coins.
  - Flags **duplicate addresses** (the same address found in 2+ files — strong evidence it's a real wallet).
  - Flags **multi-coin files** (a file with addresses for 2+ different coins — looks like a real wallet app backup).
  - Flags **coverage gaps** (supported coins not found in a file that already matched at least one coin) — phrased as a nudge to double-check, not a claim the wallet holds those coins.
- **Usage**:
  ```bash
  python tools/build_wallet_graph.py <input_file> <output_file>
  ```
**Example**:
  ```bash
  python tools/build_wallet_graph.py ./output/checks/wallet_balances.json ./output/checks/wallet_relationships.json
  ```

---

### 5. Hidden/Encrypted Volume Detector (`detect_hidden_volumes.py`)

**Standalone tool -- not part of the default pipeline run** (`run_pipeline.py`
does not call it). Run it deliberately against a mounted drive/directory you
suspect may contain an old encrypted container (e.g. VeraCrypt/TrueCrypt).

- **Purpose**: Flags files that look like encrypted-container volumes, so you can
  check drives/backups for hidden wallets you might otherwise miss.
- **How it works**: Encrypted containers are designed to look like random data --
  no recognizable file header, and byte content indistinguishable from noise. This
  tool flags a file only when it matches **all** of:
  - larger than a configurable size floor (default 1 MB) -- cheap, read-free check;
  - file size is an exact multiple of 512 bytes (the disk-sector size VeraCrypt/TrueCrypt containers are sized in);
  - no recognized file-type signature (PNG, ZIP, PDF, etc.) in its header;
  - high Shannon entropy (near-random byte distribution) sampled from the file's head, middle, and tail -- **never the whole file**, so this stays fast even against multi-GB/multi-TB files.

  **This is a heuristic, not a certainty.** Some legitimately compressed or
  already-encrypted files can also read as high-entropy and get flagged. Treat
  every result as "worth a manual look," not a confirmed finding.

  **Scope boundary:** this tool only detects and flags candidates, and prints
  guidance for attempting a manual mount. **It never attempts to guess,
  brute-force, or crack a password itself.** If you believe a flagged file is a
  real VeraCrypt/TrueCrypt volume, you attempt the mount yourself with your own
  remembered password.
- **Usage**:
  ```bash
  python tools/detect_hidden_volumes.py <start_path> <output_file>
  ```
**Example**:
  ```bash
  python tools/detect_hidden_volumes.py /Volumes/OldDrive ./output/hidden_volumes.json
  ```

---

### 6. Transaction Graph Crawler (`crawl_transaction_graph.py`)

**Standalone tool, Bitcoin-only in v1 -- not part of the default pipeline run.**
Given one known Bitcoin address, discovers other addresses likely owned by the
same person using **public blockchain data only** (no private keys involved).

- **Purpose**: Starting from a wallet you've already found, trace outward to find
  other "sitting" wallets -- e.g. addresses you mined to and later transferred
  from, that may still hold a balance.
- **How it works**: Two signals, clearly distinguished in the output:
  - **Co-spend (high confidence)**: if your address was used as one of several
    inputs on the same transaction, the other input addresses were *necessarily*
    signed by the same wallet -- you need every input's private key to build a
    transaction. This is the standard technique for clustering addresses without
    needing any keys.
  - **Output-following (lower confidence)**: addresses that received funds *from*
    your address are also followed, but only when that transaction has a small
    number of outputs. Transactions with a large number of outputs (mining-pool
    payouts, exchange batch withdrawals) are skipped entirely -- following those
    would sweep in hundreds of unrelated people's addresses, not yours.
  - The crawl is bounded (`--generations`, default 2; `--max-addresses`, default
    200) so it can't run away on a busy address.
  - Every address's report line also shows its **last activity** (years since its
    most recent confirmed transaction), with an explicit call-out on anything
    dormant 5+ years -- not a claim about what happened, just the real blockchain
    record so you can check it against what you remember.
- **Usage**:
  ```bash
  python tools/crawl_transaction_graph.py <seed_address> <output_file> [--generations N] [--max-addresses N] [--threshold BTC]
  ```
**Example**:
  ```bash
  python tools/crawl_transaction_graph.py 1YourFoundAddressHere ./output/cluster.json --generations 2 --threshold 1.0
  ```

---

### 7. Seed-Phrase Finder (`find_seed_phrases.py`)

**Standalone tool -- not part of the default pipeline run.** Scans text files
for candidate BIP39 seed phrases (the 12/15/18/21/24-word backup phrases used
by nearly all modern wallets -- Electrum, Exodus, hardware wallets, and more).

- **Purpose**: Help find backup seed phrases you wrote down somewhere on an old
  drive, so they can be tried against known wallets.
- **How it works**: Every BIP39 phrase's last word encodes a **checksum** of the
  preceding words. This tool doesn't just look for runs of words that happen to
  be in the BIP39 wordlist (which would false-positive constantly on ordinary
  text) -- it validates the actual checksum via the `mnemonic` library (the
  standard, audited Python BIP39 implementation), so only sequences that are
  cryptographically valid mnemonics are flagged. Still a heuristic worth a
  manual look, not an absolute certainty.
- **Security note**: a valid seed phrase IS the private key material for a
  wallet. This tool **never prints found phrase text to the console** -- only a
  count per file. The actual phrase text is written only to your local output
  JSON file, which is the real deliverable; keep that file private.
- **Scope (v1)**: plain text files only. Images (e.g. photographed handwritten
  backups) aren't scanned -- that would need OCR, which is a separate,
  not-yet-built capability.
- **Usage**:
  ```bash
  python tools/find_seed_phrases.py <start_path> <output_file>
  ```
**Example**:
  ```bash
  python tools/find_seed_phrases.py /Volumes/OldDrive ./output/seed_phrases.json
  ```

---

### 8. Seed-Phrase Matcher (`match_seed_phrases.py`)

**Standalone tool -- not part of the default pipeline run.** Takes candidate
seed phrases (e.g. from `find_seed_phrases.py`'s output) and tries them
against real accounts.

- **Purpose**: Turn a candidate backup phrase into an answer -- does it
  actually produce a wallet with money in it?
- **How it works**: Derives addresses using the standard HD-wallet derivation
  schemes (`bip_utils` -- an audited BIP32/39/44/49/84 library, not hand-rolled
  crypto math): BIP44/BIP49/BIP84 for Bitcoin, BIP44 for Ethereum and
  Litecoin. Checks the first several addresses (default 5) on each scheme for
  a balance, reusing this project's existing balance-check services and
  retry logic.
  - **v1 scope**: this bounded scheme set won't catch every possible old
    wallet -- some very old software (pre-BIP32 Bitcoin Core, old Electrum
    versions) used nonstandard schemes. A more exhaustive "deep dive" mode is
    planned as a future, separately-run tool for exactly this situation.
  - **Never computes or outputs a private key.** Only public addresses and
    their balances. If a match is found, you re-derive the actual spending
    key yourself in trusted wallet software (Electrum, a hardware wallet,
    etc.), now knowing which phrase/scheme/index to use.
- **Security note**: pass phrases only via a file -- **never** as a
  command-line argument (visible in shell history and `ps aux`). Found phrase
  text is never printed to the console; it's written to your local output
  file only, and only for phrases that actually produced a balance (phrases
  with nothing found are reported by index, not repeated in the output).
- **Usage**:
  ```bash
  python tools/match_seed_phrases.py <phrases_file> <output_file> [--num-addresses N]
  ```
**Example**:
  ```bash
  python tools/match_seed_phrases.py ./output/seed_phrases.json ./output/matches.json
  ```

---

### 9. Wallet Unlock via BTCRecover (`unlock_wallet.py`)

**Standalone tool -- not part of the default pipeline run.** Wraps
[BTCRecover](https://github.com/3rdIteration/btcrecover) (the actively
maintained Python 3 fork -- the original `gurnec/btcrecover` is Python 2-only
and does not run today) to test candidate passwords against a real wallet
file (Bitcoin Core, Armory, Electrum, and many others -- see BTCRecover's own
README for the full supported list).

- **Install**: `bash scripts/install_btcrecover.sh` -- clones/updates
  BTCRecover into `vendor/btcrecover/` (not committed to this repo; it's a
  separate GPLv2 project) and installs its dependencies.
- **⚠️ Critical: the real recovery run must happen offline.** BTCRecover ships
  its own `SKILL.md` (`vendor/btcrecover/SKILL.md`) written specifically for
  AI coding agents, which documents the *separation principle*: a single
  online machine/session must never hold both the wallet file and the
  password candidates in a way that could unlock funds while still connected
  to the network. `unlock_wallet.py` enforces this with a hard safety gate --
  it checks network connectivity and **refuses to run** unless the machine is
  verified offline, or you explicitly pass `--allow-online` (only appropriate
  for known-safe test/example data, never a real wallet). **Read
  `vendor/btcrecover/SKILL.md` before running this against a real wallet.**
- **Usage** (candidates come from a file only -- never pass a password as a
  command-line argument):
  ```bash
  # 1. Install (online is fine)
  bash scripts/install_btcrecover.sh

  # 2. Disconnect network (Wi-Fi off, Ethernet unplugged, no hotspot)

  # 3. Run the real recovery (offline)
  python tools/unlock_wallet.py <wallet_path> <candidates_file>
  ```
- On success, BTCRecover's complete output is shown to you as-is (including
  its donation/tip-address block) -- this tool never intercepts, condenses,
  or paraphrases it.

---

### 10. Full wallet.dat Scanner (`scan_wallet_dat.py`)

**Standalone tool -- not part of the default pipeline run.** `analyze_wallets.py`
finds addresses by regex-matching *text* in a file -- which only catches
addresses that happen to be stored as readable label text. A Bitcoin Core
`wallet.dat` typically stores hundreds or thousands of addresses as raw
binary key records instead, which a text regex will never find. This tool
properly parses the wallet's actual Berkeley DB structure to enumerate
**every** address in it.

- **Purpose**: Check every address a wallet file actually contains, not just
  the handful that happen to be regex-matchable.
- **How it works**: Walks the wallet's Berkeley DB btree structure directly
  and decodes Bitcoin Core's own record format. **Safety property, enforced
  structurally, not just by convention:** every address this tool needs
  (from both "key" records and "name"/label records) lives in the database
  *key* half of each record -- the *value* half, where private keys are
  stored, is skipped via position arithmetic and is **never read from disk**
  during a scan. This isn't a "don't print it" rule like the seed-phrase
  tools -- the private key bytes never enter memory in the first place.
- If the wallet has `ckey` (encrypted) records, this tool still finds those
  addresses (safe -- public keys only) but reports that a password is needed
  to actually spend from them (see `unlock_wallet.py`).
- **Usage** (checking potentially hundreds of addresses live can take a
  while and press against API rate limits -- use `--limit` for a bounded
  first pass):
  ```bash
  python tools/scan_wallet_dat.py <wallet_path> <output_file> [--limit N]
  ```
**Example**:
  ```bash
  python tools/scan_wallet_dat.py ~/wallets/Bitcoin/wallets/mywallet/wallet.dat ./output/wallet_scan.json --limit 50
  ```

---

## Is It Actually Recoverable?

Not every found wallet is a self-custody wallet you hold the keys to -- some
may turn out to be old exchange or custodial-service balances, which this
project's tools can't recover directly (no password/seed helps if you never
held the keys). See
[`docs/wallet_recovery_reference.md`](docs/wallet_recovery_reference.md) for
a reference on which wallet software this project supports recovering
(Bitcoin Core, Electrum, Armory, and more via BTCRecover), well-known defunct
exchanges/services to cross-check against your own memory, and how to use
this project's dormancy/clustering output to help tell the two apart.

---

### 11. Fork Coin Checker (`check_fork_coins.py`)

**Standalone tool -- not part of the default pipeline run.** A hard fork
copies the entire ledger, so any address that held BTC at a fork's snapshot
controls the identical balance on the forked chain too, under the same
private key. This tool checks addresses you've already found against those
fork coins -- free money to check for, no new derivation needed.

- **Checks**: Bitcoin Cash, Bitcoin Gold (both already have services in this
  project). Bitcoin SV shares the address format too but has no service here
  yet -- a stated gap, not a silent one.
- **Input**: accepts `scan_wallet_dat.py`'s output, `crawl_transaction_graph.py`'s
  output, or a plain newline-separated address list -- composes directly with
  this project's other tools.
- **Usage**:
  ```bash
  python tools/check_fork_coins.py <addresses_file> <output_file>
  ```
**Example**:
  ```bash
  python tools/check_fork_coins.py ./output/wallet_scan.json ./output/fork_coins.json
  ```

---

### 12. Exodus Wallet Unlock via hashcat (`unlock_exodus_wallet.py`)

**Standalone tool -- not part of the default pipeline run.** BTCRecover does
not support Exodus desktop wallets. This tool wraps
[hashcat](https://hashcat.net/hashcat/) instead -- hashcat has first-class,
natively supported mode `28200` ("Exodus Desktop Wallet (scrypt)") -- plus
hashcat's own official `exodus2hashcat.py` extraction script, to test
candidate passwords against an Exodus wallet's `seed.seco` file.

- **Install**: `bash scripts/install_exodus_tools.sh` -- installs hashcat
  (via Homebrew on macOS) and fetches `exodus2hashcat.py` from hashcat's own
  repo into `vendor/hashcat-tools/` (not committed).
- **⚠️ Critical: same offline requirement as `unlock_wallet.py`.** Testing
  real passwords against a real wallet must happen with network disabled.
  `unlock_exodus_wallet.py` reuses the exact same safety gate as
  `unlock_wallet.py` -- it refuses to run unless the machine is verified
  offline, or you explicitly pass `--allow-online` (only for known-safe test
  data, never a real wallet).
- **Usage** (candidates come from a file only -- never pass a password as a
  command-line argument):
  ```bash
  # 1. Install (online is fine)
  bash scripts/install_exodus_tools.sh

  # 2. Disconnect network

  # 3. Run the real recovery (offline)
  python tools/unlock_exodus_wallet.py <path-to-seed.seco> <candidates_file>
  ```
- On success, hashcat's own output is shown as-is, same "never condense or
  paraphrase" principle as `unlock_wallet.py`.

---

### 13. Google Drive Adapter (`scan_google_drive.py`)

**Standalone tool -- not part of the default pipeline run.** Slow-crawls
your Google Drive for wallet-like files (same name/size heuristic as
`search_wallets.py`) and downloads matches directly to local disk, so every
other tool in this project can scan them exactly like a local drive.

- **Why a separate OAuth setup, not just "search Drive":** file content
  needs to flow directly from Google's servers to your local disk, the same
  way every other tool in this project handles data -- never through an AI
  assistant's own context along the way, which is exactly the kind of
  online-secret-exposure this project's other tools are careful to avoid
  (see `unlock_wallet.py` and `unlock_exodus_wallet.py`'s offline
  requirements). A metadata-only search (filenames/sizes) is fine either
  way; actual file *content* is not.
- **Setup** (one-time, in your own Google account):
  1. Go to the [Google Cloud Console](https://console.cloud.google.com/),
     create a project (or use an existing one).
  2. Enable the **Google Drive API** for that project.
  3. Create an **OAuth client ID** credential of type **Desktop app**.
  4. Download the credential JSON and save it as `credentials.json` in this
     project's root (gitignored -- never commit it).
  5. First run opens a browser for one-time consent; a `token.json` is
     cached afterward (also gitignored) so you don't need to re-consent
     every run.
- **What it does NOT do**: read the content of native Google Docs/Sheets/
  Slides (e.g. a note titled "wallet" with a seed phrase typed into it) --
  those aren't downloadable files in the same sense. Review documents like
  that directly in Drive yourself; this is a stated gap, not a silent one.
- **Usage**:
  ```bash
  python tools/scan_google_drive.py <output_dir> [--query "..."]
  ```
**Example**:
  ```bash
  python tools/scan_google_drive.py ./output/drive_downloads
  # then run the other tools against what it found, e.g.:
  python tools/find_seed_phrases.py ./output/drive_downloads ./output/drive_seed_phrases.json
  ```

---

## Pipeline Overview

```mermaid
flowchart TD
    accTitle: coin-finder tool pipeline
    accDescr: Default pipeline stages plus standalone tools that feed into or branch off it

    A[search_wallets.py] --> B[analyze_wallets.py]
    B --> C[check_wallet_balances.py]
    C --> D[filter_wallets.py]
    C --> E[build_wallet_graph.py]
    D --> F[filtered_wallets.json]
    E --> G[wallet_relationships.json/.md]

    subgraph Default pipeline [run_pipeline.py]
        A
        B
        C
        D
        E
    end

    subgraph Standalone tools
        H[detect_hidden_volumes.py]
        I[crawl_transaction_graph.py]
        J[find_seed_phrases.py]
        K[match_seed_phrases.py]
        L[unlock_wallet.py]
        M[scan_wallet_dat.py]
        N[check_fork_coins.py]
        O[unlock_exodus_wallet.py]
        P[scan_google_drive.py]
    end

    C -.public addresses found.-> I
    J -->|candidate seed phrases| K
    K -.no match.-> L
    M -.every address in a wallet.dat.-> C
    M -.ckey records found, need password.-> L
    P -->|downloaded files| A
    P -->|downloaded files| J
    D -.found wallet file, need password.-> L
    M -->|found addresses| N
    I -->|found addresses| N
```

The default pipeline (`run_pipeline.py`) runs stages A-E automatically.
Everything under "Standalone tools" is invoked deliberately, on its own,
against whatever the earlier stages (or your own manual digging) turned up --
they are not run automatically.

### Search
Identifies potential wallet files in a specified directory.

### Analyze
Extracts wallet addresses from the identified files.

### Check Balances
Fetches the balances for the extracted wallet addresses.

### Relationship Graph
Correlates wallets and coins across all discovered files, producing
`wallet_relationships.json` (the graph) and `wallet_relationships.md` (a
human-readable report) — highlighting duplicate addresses, multi-coin files, and
coverage gaps worth a second look.

### Output
Generates JSON files at each stage for traceability and easy debugging.

---

## Supported Cryptocurrencies
# Supported Cryptocurrencies

| Cryptocurrency       | Address Format (Regex)                                                                                   | API Provider For Checker               |
|-----------------------|---------------------------------------------------------------------------------------------------------|---------------------------------------|
| **Bitcoin (BTC)**     | `1[a-km-zA-HJ-NP-Z1-9]{25,34}|bc1[q|p|z][a-zA-HJ-NP-Z0-9]{38,64}`                                        | Blockstream API                       |
| **Bitcoin Cash (BCH)**| `bitcoincash:[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{42}`                                                     | Blockchair                            |
| **Bitcoin Gold (BTG)**| `[AG][a-km-zA-HJ-NP-Z1-9]{26,33}`                                                                       | Blockchair                            |
| **Cosmos (ATOM)**     | `cosmos1[a-z0-9]{38}`                                                                                   | Mintscan                              |
| **Ethereum (ETH)**    | `0x[a-fA-F0-9]{40}`                                                                                     | Etherscan API                         |
| **Ethereum Classic**  | `0x[a-fA-F0-9]{40}`                                                                                     | Blockscout                            |
| **Dogecoin (DOGE)**   | `D{1}[5-9A-HJ-NP-U]{1}[1-9A-HJ-NP-Za-km-z]{32}`                                                         | SoChain API                           |
| **Shiba Inu (SHIB)**  | `0x[a-fA-F0-9]{40}`                                                                                     | Etherscan API                         |
| **Litecoin (LTC)**    | `[LM3][a-km-zA-HJ-NP-Z1-9]{26,33}`                                                                      | Blockcypher API                       |
| **Ripple (XRP)**      | `r[1-9A-HJ-NP-Za-km-z]{25,35}`                                                                          | XRPL.org                              |
| **IOTA (MIOTA)**      | `[A-Z9]{81}`                                                                                           | IOTA Tangle Explorer                  |
| **Tether (USDT)**     | `0x[a-fA-F0-9]{40}` (Ethereum) or `1[a-km-zA-HJ-NP-Z1-9]{25,34}` (Bitcoin Omni Layer)                   | Etherscan or Omni Explorer            |
| **Helium (HNT)**      | `13[a-zA-Z0-9]{45,48}`                                                                                 | Helium Explorer                       |
| **Cardano (ADA)**     | `addr[a-z0-9]{58,90}`                                                                                  | Blockfrost API                        |
| **Zcash (ZEC)**       | `t[1-9A-HJ-NP-Za-km-z]{34}`                                                                            | Zcash Explorer                        |
| **OKCash (OK)**       | `[0-9A-Za-z]{34}`                                                                                      | OKCash Blockchain Explorer            |
| **Binance Coin (BNB)**| `bnb[a-z0-9]{38}`                                                                                      | Binance Explorer                      |
| **Monero (XMR)**      | `[48]{1}[0-9AB][1-9A-HJ-NP-Za-km-z]{93}`        

---

## Configuration

### 1. Search Config (`config/search.py`)

- **Purpose**: Specifies file extensions and keywords to search for potential wallet files.
- **Example**:
  ```python
  WALLET_EXTENSIONS = [".dat", ".key", ".wallet", ".json", ".backup"]
  WALLET_KEYWORDS = ["wallet", "crypto", "bitcoin", "ethereum", "backup"]
  ```
  ---

### 2. Analyze Config (`config/analyze.py`)
- **Purpose**: Specifies file extensions and keywords to search for potential wallet files.
- **Example**:
  ```python
  WALLET_EXTENSIONS = [".dat", ".key", ".wallet", ".json", ".backup"]
  WALLET_KEYWORDS = ["wallet", "crypto", "bitcoin", "ethereum", "backup"]
  ```
  ---

### 3. Analyze Config (`config/analyze.py`)
- **Purpose**: Specifies file extensions and keywords to search for potential wallet files.
- **Example**:
  ```python
  WALLET_EXTENSIONS = [".dat", ".key", ".wallet", ".json", ".backup"]
  WALLET_KEYWORDS = ["wallet", "crypto", "bitcoin", "ethereum", "backup"]
  ```
  ---
  
## Environment Setup

### Required Environment Variables

### **`.env` File**:
```python
ETHERSCAN_API_KEY=your_etherscan_api_key 
BLOCKFROST_API_KEY=your_blockfrost_api_key
```


---

## Changes With and Without Environment Setup

- **With Environment Setup**:
  - APIs requiring authentication (e.g., Etherscan, Blockfrost) work seamlessly.
- **Without Environment Setup**:
  - Tools dependent on API keys will fail, displaying appropriate error messages.

---

## Failsafes

1. **Invalid Coins**:
   - If unsupported coins are passed via `--coins`, the tool reports them and exits gracefully.

2. **API Errors**:
   - If an API call fails (e.g., rate limits, connectivity), the script retries up to 3 times before giving up on that address -- a single flaky call is never enough to write a wallet off. Addresses still inconclusive after retries are recorded in `inconclusive_balances.json` (alongside `wallet_balances.json`) so they stay visible as "needs a recheck" instead of silently disappearing.

3. **File Processing Errors**:
   - If a file cannot be read (e.g., permission issues), the error is logged, and processing continues.

4. **Empty Results**:
   - If no wallets or balances are found, the output files are still created but remain empty.

---

## Adding New Coins

### Extend `wallet_config.py`

- Add the new cryptocurrency and its corresponding service file:
```python
  WALLET_SERVICES["NewCoin"] = "newcoin"
```

**Example**:
```python
WALLET_SERVICES = {
    "Binance Coin": "binance_coin",
    "Bitcoin": "bitcoin",
    "Cardano": "cardano",
    "Dogecoin": "dogecoin",
    "Ethereum": "ethereum",
    "Litecoin": "litecoin",
    "Monero": "monero",
    "Ripple": "ripple",
    "Shiba Inu": "ethereum",
    "Tether": "ethereum",
}
```

### Implement Service

- Implement the service for the new cryptocurrency.

  Create the Service
Create services/newcoin.py and implement the WalletService interface:

```python
from . import WalletService

class NewCoinService(WalletService):
    def check_balance(self, address):
        # Implement API or node integration to fetch balance
        pass
```
### Add Patterns (if needed) 
Add regex patterns for the new coin in analyze_config.py.
```python
CRYPTO_PATTERNS["NewCoin"] = r"regex_pattern_for_new_coin"
```
**Example**:
```python
CRYPTO_PATTERNS = {
    "Bitcoin": r"(1[a-km-zA-HJ-NP-Z1-9]{25,34}|bc1[q|p|z][a-zA-HJ-NP-Z0-9]{38,64})",
    "Bitcoin Cash": r"bitcoincash:[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{42}",
}
```
