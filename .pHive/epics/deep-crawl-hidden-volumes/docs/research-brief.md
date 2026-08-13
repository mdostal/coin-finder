# Research Brief: Deep-Crawl + Hidden/Encrypted Volume Detection

## Requirement

North-star `avoid`/goal items (`.pHive/project-profile.yaml`): "be as accurate and
thorough as possible when crawling multi-terabyte drives and backups... flag hidden
drives, encrypted areas, etc that we may want to attempt a check for an old
VeraCrypt or TrueCrypt or such drive and see if we can find partitions and then
allow the user to attempt to unlock them." Now concretely motivated: the user has
real old hard drives with potentially real, valuable wallets on them.

## Codebase findings

- `config/search.py::MAX_FILE_SIZE = 45 * 1024 * 1024` (45 MB) — `search_wallets.py`
  **skips every file above this size**. Real VeraCrypt/TrueCrypt containers and disk
  images are routinely far larger than 45 MB (often GB+). The existing search stage
  structurally cannot find them — this isn't a bug to fix in that stage, it's a
  different kind of scan needing its own tool with no upper size bound, only
  sampled reads (never loading a multi-GB file fully into memory).
- No existing code touches file entropy, magic-byte signatures, or disk/volume
  enumeration anywhere in the repo. This is wholly new capability.
- `tools/filter_wallets.py`-style single-responsibility tool pattern (established in
  epic `wallet-relationship-graph`) is still the right shape: a pure detection
  function + a directory walker + a thin CLI.

## Detection technique (this is real, established forensic practice, not invented)

Encrypted containers (VeraCrypt/TrueCrypt volumes in particular) are designed to be
indistinguishable from random data — no magic-byte header, no recognizable
structure. The standard heuristic (used by real tools like `tchunt`/`tchunt-ng`) is:

1. **No recognized file-type signature** — check the first bytes against a small
   table of common magic-byte headers (PNG, JPEG, ZIP, PDF, GZIP, ELF/PE, SQLite,
   etc.). A match means it's a known, explainable format — not a candidate.
2. **High Shannon entropy** across the file (sampled head/middle/tail chunks, not
   the whole file, to stay fast on huge files) — random/encrypted data sits very
   close to the theoretical maximum (8.0 bits/byte); most real file formats,
   including many compressed ones, measurably don't.
3. **Size is a multiple of 512 bytes** — VeraCrypt/TrueCrypt volumes are sized in
   whole disk sectors. A cheap, free extra signal.
4. **Minimum size floor** — tiny files aren't worth flagging; a configurable floor
   (default 1 MB) cuts noise.

**Known limitation, stated up front:** this is a heuristic, not a certainty. Some
legitimately compressed/already-encrypted files (some video, some archives) can
also read as high-entropy and trigger a false positive. The output is a candidate
list for the user to manually judge, not a definitive finding — same conservative
framing epic `wallet-relationship-graph` used for `coverage_gaps`.

## Explicit scope boundary (confirmed before writing any code)

The requirement text says "...allow the user to attempt to unlock them." This tool
will **detect and flag** candidates and print guidance on how the user can attempt
a mount themselves with their own VeraCrypt/TrueCrypt installation and their own
remembered passwords. It will **not** attempt to guess, brute-force, or crack
passwords — that's a different, much higher-risk category of tool and isn't what
was actually asked for (the ask was "flag... and allow the user to attempt", not
"crack it for me").

**Deferred, not in this epic:** live disk/partition enumeration (e.g. `diskutil
list` on macOS) to find drives/partitions not currently mounted at all. That's
OS-specific, higher-risk to get subtly wrong, and unverifiable in this environment
without the user's actual hardware in front of me. This epic covers **files within
an already-mounted/accessible directory tree** (which is how the user will actually
access old drives — mount via USB, then scan the mounted path) — realistic for the
stated use case without overreaching into unverified platform-specific territory.

## Cross-cutting concerns loaded

`documentation` — applies: new standalone tool, new heuristic, scope boundary all
need README coverage.

## Confidence

High on the entropy/magic-byte technique (well-established, verifiable via unit
tests with synthetic byte buffers — no real drive access needed to validate the
logic). Explicitly lower confidence flagged on real-world false-positive rate
against the user's actual old drives — that can only be validated once they run it,
which is exactly what they said they want to do next.
