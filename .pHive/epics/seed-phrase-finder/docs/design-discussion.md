# Design Discussion: Seed-Phrase Finder

**Process note:** same no-live-teammates adaptation as prior epics.

## 1. What Are We Doing?

User request: "build the backup seed lists and such as well -- help FIND those
on hard drives." Scan text files for candidate BIP39 seed phrases (12/15/18/21/
24-word mnemonics used by nearly all modern wallets -- Electrum, Exodus,
hardware wallets, etc.) so they can be tried against wallets in a later epic
(HD derivation / credential matching).

## 2. Approach

1. **New dependency**: `mnemonic` (added to `requirements.txt`, production dep)
   -- the standard Python BIP39 library. Provides the official 2048-word
   English wordlist and, critically, **checksum validation**
   (`Mnemonic.check()`): a real BIP39 mnemonic's last word encodes a checksum
   of the preceding entropy. Random English prose containing a run of
   BIP39-wordlist words will almost never pass this checksum check --
   dramatically fewer false positives than "all words are in the wordlist"
   alone would give. Reusing an audited implementation rather than
   hand-rolling checksum math, per the established "audited library for
   anything touching key material" agreement.
2. **`tools/find_seed_phrases.py`**:
   - `extract_words(text)` -- tokenize to lowercase words, strip punctuation.
   - `find_candidate_phrases(text)` -- slide a window over every valid mnemonic
     length (12, 15, 18, 21, 24) across the tokenized words, and keep any
     window where `Mnemonic("english").check(phrase)` passes. Returns
     `[{"phrase": ..., "word_count": N}, ...]`.
   - `scan_directory(start_path, max_file_size=10_000_000)` -- walks the
     directory (mirrors `search_wallets.py`'s traversal), reads each file as
     text (`errors="ignore"`, matching the codebase's existing decode
     convention), skips files above `max_file_size` (large files are very
     unlikely to be short handwritten notes and would be slow to tokenize).
     Returns `{file_path: [candidate phrase dicts]}`.
3. **Security-critical output rule**: a valid BIP39 mnemonic IS private key
   material -- it deterministically derives real wallets. The CLI **never**
   prints found phrase text to stdout (only a count: `"Found N candidate
   phrase(s) in <file> -- see <output_file>"`). The phrase text is written
   only to the local output JSON file, which is the actual deliverable for the
   user -- same handling discipline already established for wallet.dat
   contents earlier in this session.
4. **Scope boundary, stated up front**: text files only in v1. The user
   mentioned images with unclear content ("old images and the word ciphers")
   -- OCR'ing images for embedded seed-phrase text is a real, distinct
   capability (needs an OCR library/model) and is explicitly deferred, not
   silently dropped.

## 3. What Could Go Wrong

- **medium** -- Even with checksum validation, false positives aren't
  impossible (checksum is only 4-8 bits depending on word count, i.e. 1-in-16
  to 1-in-256 chance for a random-but-wordlist-only sequence). Framing every
  result as "worth checking," consistent with prior epics' posture.
  Downstream (HD derivation epic) will show whether a candidate actually
  derives to a real known address -- the strongest possible confirmation.
- **high** (handling risk, not detection risk) -- printing real seed-phrase
  text carelessly (stdout, logs, chat) is a real secret-exposure risk. Handled
  via the CLI output rule above; I will also not echo phrase text into this
  conversation when manually verifying the tool works.

## 4. Verification Strategy

```
VERIFICATION PLAN:
  Tools: pytest
  Automated: extract_words, find_candidate_phrases (using the well-known
    PUBLIC BIP39 test vector "abandon abandon ... about" -- a standard test
    fixture used throughout BIP39 tooling, not a real wallet), and
    scan_directory via tmp_path fixtures
  Manual: run the CLI against a tmp_path fixture containing the test vector
    embedded in surrounding prose, verifying the console output never prints
    the phrase itself (only a count) while the output file contains the full
    finding
  Not verifying: OCR/image-embedded phrases (explicitly deferred, see above)
```

## 5. Scale Assessment

```
SCALE ASSESSMENT:
  Files affected: ~3 (new tools/find_seed_phrases.py, new
    tests/test_find_seed_phrases.py, requirements.txt + README.md edits)
  RECOMMENDATION: Proceed to a single story (small, well-bounded, reuses
    established patterns from prior epics)
```
