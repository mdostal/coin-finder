# Design Discussion: Multi-Seed Crawler + Recoverability Reference

**Process note:** same no-live-teammates adaptation as prior epics. Two
small, related additions from the same user request, bundled into one epic.

## 1. What Are We Doing?

1. `crawl_transaction_graph.py`'s CLI accepted only one seed address. User
   asked for "a mix of the wallets and addresses found on disk and then any
   currently held wallets and addresses" as crawl input, so the co-spend/
   dormancy graph can rediscover a specific recalled wallet ("5 coins ...
   transferred from a mining account") that might only surface by combining
   discovery sources.
2. User asked to "match or have understanding of any of the wallets being
   things that shutdown, discontinued, etc -- to know if they are
   recoverable." Reliable automated detection of "this address belonged to
   exchange X" isn't achievable from public blockchain data alone (that
   requires proprietary attribution databases). The honest, defensible scope
   is a **reference document**, not a classifier -- explicitly scoped that
   way rather than overclaiming a capability this project can't responsibly
   deliver.

## 2. Approach

1. `crawl_wallet_cluster()` already accepted a list of seed addresses at the
   function level (unchanged since epic `transaction-graph-crawler`) -- only
   the CLI needed to change. New `load_seed_addresses(arg)`: if `arg` is an
   existing file, reads addresses one per line (blank lines / `#` comments
   ignored); otherwise treats `arg` as a single literal address. Lets one run
   combine `--seeds addresses_found_on_disk.txt` -style files with ad hoc
   single addresses, without a breaking two-mode CLI.
2. `docs/wallet_recovery_reference.md`: a curated reference table of
   self-custody wallet software this project already helps recover (Bitcoin
   Core, Electrum, Armory, others via BTCRecover) plus well-known defunct
   custodial services (Mt. Gox, MyBitcoin, Bitcoinica, early mining pools)
   for the user to cross-check against their own memory, plus a note on how
   this project's own dormancy/clustering output can help distinguish
   self-custody from custodial. Explicitly states its own scope limits up
   front rather than implying automated certainty.

## 3. What Could Go Wrong

- **low** -- `load_seed_addresses`'s file-vs-literal auto-detection could
  misfire if a real Bitcoin address string happened to collide with an
  existing file path on disk. Extremely unlikely (addresses aren't valid
  relative/absolute path shapes in practice) and low-consequence (worst case:
  an error reading a "file" that's actually meant as an address, immediately
  visible, not a silent wrong-data failure).
- **low** -- The recoverability reference could go stale (a service's status
  changes) or be incomplete (many possible defunct services aren't listed).
  Framed explicitly as a reference to cross-check, not an exhaustive or
  automatically-current database.

## 4. Verification Strategy

```
VERIFICATION PLAN:
  Tools: pytest
  Automated: load_seed_addresses() for both the single-literal and
    file-based shapes; crawl_wallet_cluster() accepting a combined multi-seed
    list (extends existing mocked-fetch test pattern, no real network calls)
  Manual: none needed for the reference doc (documentation only, no code path)
  Not verifying: the reference doc's factual completeness beyond the
    specific, well-documented historical examples cited
```

## 5. Scale Assessment

```
SCALE ASSESSMENT:
  Files affected: 4 (tools/crawl_transaction_graph.py edit,
    tests/test_crawl_transaction_graph.py edit, new
    docs/wallet_recovery_reference.md, README.md edit)
  RECOMMENDATION: Proceed to a single story
```
