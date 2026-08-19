# Design Discussion: Password / Note Scanner

## 0. Prelude

Base branch `dev`. Dedicated research pass against the live codebase (§2),
not reused guesswork.

## 1. Why now

User's own words: *"let's add another file finder for an attempt to find
seed key lists, passwords, etc -- we have 2 other things for that, but we
should also do a default one here for an attempted password scan on things
and allow us to go through and try to find these -- most of these I had
somewhere with a password stored alongside or in a note or somewhere on
the box."* Prompted directly by discovering real findings tonight with no
matched password.

Confirmed the "2 other things" don't cover this: `find_seed_phrases.py`
only matches exact BIP39 mnemonic word sequences (checksum-validated);
`web/vault.py`'s candidate matching only tries passwords already manually
typed in. Nothing today reads ordinary notes/text files looking for
password-shaped or credential-labeled strings to auto-build a candidate
list.

## 2. Ground truth: what exists today

- **`find_seed_phrases.py` is the architecturally right sibling to build
  from**, not `search_wallets.py`. It has no filename/extension allowlist
  at all — walks every file under a path, filters only on size (10MB max)
  and a binary-vs-text content sniff (first 8KB, reject on any null byte —
  the same heuristic `grep -I`/git use). `search_wallets.py`, by contrast,
  is purely filename-driven (extension or a coin-name/keyword substring in
  the *filename*) — a generic `passwords.txt` or a Notes-app export would
  almost never surface there since nothing about those filenames screams
  "wallet." The scanner needs `find_seed_phrases.py`'s shape (content-
  based, no filename gate), not `search_wallets.py`'s.
- **Zero existing password/credential-shaped regex or heuristic anywhere**
  in the codebase (confirmed by direct grep + manual review of every hit).
  This is genuinely new matching logic — not a variant of an existing one.
- **The one and only integration point into the vault is `add_vault_entry
  (name, value_file_path, description)`** (`web/vault.py`) — one name/
  value pair per call, value must be written to a local temp file first.
  There is no bulk-ingestion path; a scanner producing N candidates needs
  N such calls, each with a unique `name` (auto-unlock enumerates vault
  entries by name).
- **The candidate-match-integrity lesson (real, not hypothetical) — and
  why it does NOT transfer directly.** That epic fixed a real bug where
  garbage text (Rust-mangled symbols) coincidentally matched a pure-shape
  coin-address regex with zero structural validation, flowed unfiltered
  through analysis into a real "finding" backed by a real (wasted) API
  call. The fix relied on Base58Check-style checksums — a real, offline,
  discriminating validator. **A "password-shaped" text heuristic has no
  analogous structural check available at all.** What *does* transfer:
  (a) enumerate and fix every consumer of the new signal, not just the
  first one found, (b) measure and document the false-positive rate
  honestly rather than assume it away, (c) never patch the symptom with a
  narrow path/blocklist exclusion.
- **Asymmetric stakes vs. address matching, which changes the risk
  calculus.** A false-positive *address* becomes a bogus "finding" — a
  real external API call, a row that looks like a real recovered wallet.
  A false-positive *password candidate* becomes an extra vault entry that
  gets tried and fails — a local, free, silent no-op (`_match_vault_label`
  already handles "candidate didn't match" as the normal case). The real
  cost of over-triggering here isn't false financial signal, it's
  **volume/noise**: thousands of garbage candidates would slow down
  auto-unlock's already-sequential per-wallet trial loop and clutter the
  vault UI, not create a false "you found money" moment.

## 3. Proposed approach

**3.1 — Reuse `find_seed_phrases.py`'s file-discovery shape.** New scanner
walks every file under a target path (same no-filename-gate approach),
same size cap (10MB — a password/credential note is never larger than
that; keep consistent rather than inventing a new number), same binary-
vs-text sniff before the expensive matching pass.

**3.2 — Heuristic: keyword-proximity, not shape-matching.** Since there's
no structural validator available (§2), match on **explicit credential
labels near a value** — lines matching patterns like `password:`, `pw:`,
`pass:`, `passphrase:`, `pwd:` (case-insensitive) followed by a token, OR
a plausible password-shaped token (length/character-class heuristic) on a
line that also mentions a coin/wallet name (reusing `config/search.py`'s
existing `COIN_NAMES`/`WALLET_KEYWORDS` list as the proximity anchor,
not duplicating it). This is honestly a **best-effort, lower-precision**
signal than anything else in this pipeline — framed explicitly as
"candidates to try," never as a "finding."

**3.3 — File-type scope for v1: plain text only, explicitly NOT PDFs or
binary note-app exports.** PDF text extraction needs a new dependency
(this repo currently has zero PDF-handling dependency) and note-app export
formats (`.enex`, `.pages`) are proprietary/binary, not something the
existing text-sniff approach handles. Ship v1 against what
`find_seed_phrases.py`'s exact same file-discovery already handles well
(plain text, markdown, code/config files, anything that survives the
binary sniff) and explicitly document PDF/note-export support as future
scope, not silently absent — same "no silent coverage claims" discipline
`candidate-match-integrity` established for validator gaps.

**3.4 — Vault ingestion: loop `add_vault_entry` with deterministic,
collision-safe naming.** Name each discovered candidate deterministically
from its source (e.g. `note-scan-{content-hash-prefix}`) so re-running the
scanner against the same file doesn't create duplicate vault entries every
time, and so a name collision across two different files' candidates
can't silently overwrite one with the other.

**3.5 — Never auto-record a "finding."** This scanner's output is
candidate *passwords*, which only ever flow into the vault → auto-unlock
pipeline. It must never call `record_finding()` or anything that could
make a discovered password candidate look like a recovered balance —
keeping the "candidate vs. finding" distinction the rest of this app
already relies on intact.

## 4. Risks

| Risk | Mitigation |
|---|---|
| Keyword-proximity heuristic has a real, honestly-unknown false-positive rate (no checksum to fall back on) | Frame every discovered candidate explicitly as "candidate to try," never a finding; measure real FP rate against a real test corpus during implementation and document it plainly (candidate-match-integrity's "no silent coverage claims" discipline) rather than assert it's solved |
| A noisy/high-volume scan could flood the vault with garbage candidates, slowing auto-unlock's sequential per-wallet trial loop | Cap candidates per scan run at a sane ceiling and surface the count to the user before bulk-adding to vault (a confirm step, not silent auto-ingestion) |
| Duplicate vault entries on repeated scans of the same files | Deterministic content-hash-based naming (§3.4) |
| Same class of "only fixed the first consumer" bug candidate-match-integrity found | Only one consumer exists today (`add_vault_entry`) — confirmed via research, not assumed; if a second consumer is added later it must go through the same confirm-before-ingest gate |

## 5. Scale assessment

**Medium.** New scanner module (parallel to `find_seed_phrases.py`, not a
modification of it), a new web route + confirm-before-ingest UI flow, and
vault integration. Contained to a well-understood existing subsystem
(vault/candidate matching), no new external service. Proceeding to a
lightweight vertical plan, no full structured outline required.
