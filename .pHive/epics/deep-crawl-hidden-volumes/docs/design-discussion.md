# Design Discussion: Deep-Crawl + Hidden/Encrypted Volume Detection

**Process note:** same no-live-teammates adaptation as prior epics.

## 1. What Are We Doing?

The user has real old hard drives that may contain forgotten wallets, and
explicitly wants encrypted-container/hidden-volume detection now that the earlier
two epics landed. `search_wallets.py` structurally can't help here — it skips
anything over 45 MB, and encrypted containers are usually far bigger. Done = a new,
standalone tool that walks a directory tree (a mounted drive), flags files that
look like VeraCrypt/TrueCrypt-style encrypted containers using the
entropy+magic-byte heuristic from the research brief, and prints a report with
manual-mount guidance. Explicitly NOT building password guessing/cracking — see
research-brief.md's scope-boundary section.

## 2. What I Found

See research-brief.md. Key constraint: `MAX_FILE_SIZE` in the existing search
pipeline makes this necessarily a separate tool, not a modification to
`search_wallets.py` — different performance profile (must sample, never fully
read, multi-GB files) and different purpose (opaque containers, not text/JSON
wallet files). `tools/filter_wallets.py`'s single-responsibility pattern still
applies to the new tool's shape.

## 3. My Proposed Approach

1. **`tools/detect_hidden_volumes.py`** — pure, side-effect-free core:
   - `shannon_entropy(data: bytes) -> float` — standard byte-level entropy calc,
     returns bits/byte (0.0–8.0).
   - `KNOWN_SIGNATURES` — a small table of magic-byte headers (PNG, JPEG, GIF, ZIP,
     GZIP, PDF, ELF, MZ/PE, SQLite, 7z, RAR) mapped to format names.
   - `has_known_signature(header_bytes: bytes) -> str | None` — returns the matched
     format name, or `None`.
   - `looks_like_encrypted_container(file_path, min_size_bytes=1_000_000,
     entropy_threshold=7.9, sample_size=65536) -> dict | None` — reads only the
     file's size (stat) plus head/middle/tail samples (never the whole file for
     large files); returns a result dict (`{path, size, entropy, size_is_sector_multiple}`)
     when it's a candidate, `None` otherwise. All four heuristic conditions from
     the research brief must hold.
2. **Directory walker** — `scan_for_hidden_volumes(start_path) -> list[dict]`,
   `os.walk`-based (mirrors `search_wallets.py`'s traversal style), calling
   `looks_like_encrypted_container` per file, collecting non-`None` results. No
   upper file-size skip (unlike `search_wallets.py`) — that's the entire point.
3. **Report renderer** — `render_hidden_volumes_report(candidates: list[dict]) ->
   str`: lists each candidate with size/entropy, framed as "worth checking," plus a
   fixed guidance block on attempting a manual mount (`veracrypt --mount <file>` /
   `veracrypt --text --mount`), explicitly stating this tool does not attempt to
   unlock anything itself.
4. **CLI**: `python tools/detect_hidden_volumes.py <start_path> <output_file>`,
   writing the JSON candidate list; report goes to a sibling `.md` file (mirrors
   `build_wallet_graph.py`'s two-output pattern from epic 1).
5. **Not wired into `run_pipeline.py`** — deliberately standalone. This is a
   heavier, different-purpose scan (reads more bytes per file, no coin-address
   matching) the user runs deliberately against a drive they suspect has
   containers, not part of the default fast wallet-search path.
6. **Tests**: synthetic byte buffers for entropy/signature/compound-heuristic
   functions (no real files needed); `tmp_path`-based tests for the walker (a few
   small real temp files: one high-entropy "container-like" blob, one normal text
   file, one with a known magic byte).
7. **README**: new tool section + explicit scope-boundary statement (detect/flag
   only, no cracking).

## 4. What Could Go Wrong

- **high** — False positives are inherent to this heuristic (research-brief.md).
  Mitigating by: framing every report line as "worth checking," never "this is
  encrypted"; documenting the known-limitation explicitly in the README so the
  user doesn't over-trust it against their real drives.
- **medium** — Reading `sample_size` bytes at three offsets (head/middle/tail) of
  every file in a huge, multi-TB drive tree is still a lot of I/O even without
  loading whole files. Accepting this for v1 — it's still vastly cheaper than full
  reads, and the user explicitly asked for thoroughness over speed. A `min_size_bytes`
  floor (default 1 MB) cuts out the bulk of small files cheaply (stat-only, no read).
- **medium** — This is genuinely new, unvalidated-against-real-data logic (unlike
  epics 1–2, which touched existing, exercised code paths). Flagging directly: the
  synthetic-buffer tests prove the *math* is right, not that the heuristic's
  false-positive rate is acceptable on the user's actual old drives. That can only
  be learned by running it, which is explicitly the next step after this epic
  ships.
- **low** — `veracrypt` CLI may not be installed on this machine; the report's
  guidance names the command but doesn't assume it's available or attempt to run
  it.

## 5. Dependencies and Constraints

- No new dependencies — stdlib only (`os`, `math` for log2, `collections.Counter`).
- No dependency on epics 1–2's code.
- Explicit non-goal, stated for the record: no password cracking/brute-forcing
  functionality, in this epic or implied as a follow-up.

## 6. Open Questions

1. `entropy_threshold=7.9` and `min_size_bytes=1_000_000` are my proposed v1
   defaults (favoring fewer false positives over catching every possible
   container) — reasonable, or would you rather start looser (more candidates,
   more manual review) given you'd rather not miss anything? I can make both
   trivially tunable via CLI flags in the next iteration if the v1 defaults miss
   things on your real drives.

## 7. Verification Strategy

```
VERIFICATION PLAN:
  Tools: pytest (existing dev dependency)
  Platforms: N/A (stdlib only, no platform-specific code)
  Automated: shannon_entropy(), has_known_signature(), looks_like_encrypted_container()
    via synthetic byte buffers (all-zero low-entropy, os.urandom high-entropy,
    known-magic-byte header, sub-floor size, non-sector-multiple size);
    scan_for_hidden_volumes() via tmp_path with a few small real temp files
  Manual: running the tool against the user's actual old hard drives -- this is
    explicitly the next step after this epic ships, and is the only real test of
    the heuristic's false-positive rate that matters
  Not verifying: real VeraCrypt/TrueCrypt mount success (this tool never attempts
    a mount itself, by design)
```

## 8. Scale Assessment

```
SCALE ASSESSMENT:
  Files affected: ~4 (new tools/detect_hidden_volumes.py, new
    tests/test_detect_hidden_volumes.py, README.md edit) -- no run_pipeline.py
    change (deliberately standalone)
  Subsystems: 1 (Python stdlib only)
  Migration required: no
  Cross-team coordination: no
  Unknowns: 1 (see Open Question -- a tuning-default question, not
    architecture-changing)

  RECOMMENDATION: Proceed to stories
  RATIONALE: Same shape as epics 1-2 -- single layer, small file count, no
    integration risk to existing pipeline since it's standalone. Small scope.
```
