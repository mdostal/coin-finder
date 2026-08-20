# Design Discussion: Wordlist Cracking Review

## 0. Prelude

Base branch `dev`. Dedicated research pass against the live codebase, plus
two real decisions confirmed directly with the user before writing this
(see §3).

## 1. Why now

User's own words, raised right after reviewing `credential-clarity-and-
unlock-ux`'s 4-state credential model: *"the next thing i'm going to have
to do if this is correct -- is literally run through rainbowtable lists
against these -- and if we FIND things that match them, a human can review
and AUTO ADD to the vault with type of pass and stuff as well in
metadata."* This is the natural next step for state 3 findings ("encrypted,
no known password") — today the only way to try a password against such a
wallet is the vault's own saved candidates; there's no way to run a
larger, user-supplied list.

## 2. Ground truth: what exists today

- **BTCRecover is already wired in** (`tools/unlock_wallet.py`), invoked
  via `subprocess.run([..., "--passwordlist", candidates_file, ...])` —
  one wallet, one plain-text candidates file (one candidate per line),
  behind a hard offline gate. This is directly reusable — the new feature
  is "point this same mechanism at a bigger, user-supplied file," not a
  new cracking integration.
- **BTCRecover's own resume support doesn't cover this app's usage.**
  `--autosave`/`--restore` explicitly do NOT work in `--passwordlist` mode
  per BTCRecover's own docs — only `--skip N` (a manual, caller-tracked
  resume point) works here, and BTCRecover doesn't persist that count for
  passwordlist runs itself. Confirmed with the user: **v1 skips pause/
  resume entirely** — BTCRecover's own `--max-eta` (defaults to 168
  hours/1 week, refuses to start otherwise) already bounds worst-case
  runtime, and a real bespoke skip-tracking layer is meaningfully more
  work than this feature's realistic v1 need justifies.
- **The once-only secret-reveal mechanism already exists and is directly
  reusable, not something to build from scratch.** `run_job(secret=True)`
  + `consume_job_result()` (one read, then the job row is deleted) +
  `web/static/secret-reveal.js` (masked-by-default, client-side toggle,
  zero extra network request) is already the pattern behind
  `auto_unlock_result.html`, `vault_reveal_result.html`,
  `extract_key_result.html`, and `password_scan_review.html`. A cracked
  password is exactly as sensitive as any of those — same mechanism,
  fifth consumer.
- **Vault provenance is a real gap, but a shallow one.** Portunus (the
  real backend, confirmed via `portunus list --json`) already supports
  arbitrary `tags` key-value metadata per secret — the gap is purely that
  `web/vault.py`'s `add_vault_entry()` never threads a `tags=` parameter
  through to `portunus drop --tags`. **The JSON fallback store** (used
  when Portunus isn't on PATH) has zero provenance support today and
  needs its own parallel extension — both backends, not just the primary
  one, per this project's established "fix every consumer" discipline
  from `candidate-match-integrity`.
- **Wordlist sourcing: confirmed user-supplied file only, nothing else.**
  Explicit user decision: *"it should be a user supplied file only, i
  don't want to touch on enabling cracking it... am iffy about putting
  that on this atm."* No auto-download of any named wordlist (rockyou.txt
  or otherwise) — not even offered as an option. This app never fetches,
  stores, or bundles a wordlist; the user brings their own file.

## 3. Confirmed decisions (resolved with the user before this doc was finalized)

1. **Wordlist source: user-uploaded file only.** No auto-download path,
   now or as a future toggle without a separate, deliberate conversation.
2. **No pause/resume in v1.** Accepted, documented limitation — bounded by
   BTCRecover's own `--max-eta` refusal-to-start ceiling.

## 4. Proposed approach

**4.1 — Upload + single-wallet crack job.** New route: pick one wallet
already flagged state-3 ("encrypted, no known password") + upload a
wordlist file (streamed to disk by Werkzeug's normal file-upload handling,
not held in the form-memory buffer this app already tuned for non-file
fields). New job kind wrapping `unlock_wallet.py`'s existing subprocess
call, pointed at the uploaded file as `candidates_file` instead of a
vault-resolved one. Same hard offline gate, unchanged — this feature gets
no exemption from it. One wallet per run, matching the state-3 framing
(a targeted attempt against a specific locked wallet), not a bulk
multi-wallet operation.

**4.2 — Review via the existing once-only-reveal pattern.** Run as
`secret=True`. Result page is the fifth consumer of the exact mechanism
already used for auto-unlock/vault-reveal/key-extraction results — masked
by default, one client-side reveal toggle, the underlying job row deleted
after the one `consume_job_result()` read. No new secrecy mechanism
invented.

**4.3 — Confirm-to-vault with provenance, never silent auto-add.** On the
review page, if a real password was found, an explicit "Add to vault"
action (human-confirmed, matching this app's established confirm-before-
ingest pattern from tonight's password-note-scanner epic) calls
`add_vault_entry` with new provenance tags: which wordlist (filename),
method (`btcrecover-wordlist-crack`), found-at timestamp, and the target
wallet path. Extend both `add_vault_entry`'s Portunus path (`--tags`) and
the JSON fallback store's schema — parity across both backends.

**4.4 — Uploaded wordlist is sensitive and temporary.** The uploaded file
may contain the user's own real candidate passwords. Never logged, saved
only for the duration of the run, deleted after — same discipline already
applied to every other candidates-file handling in this app.

## 5. Risks

| Risk | Mitigation |
|---|---|
| No pause/resume — a very large uploaded wordlist could run for a long time with no way to stop and resume cleanly | Accepted, explicitly documented limitation (§2/§3) — BTCRecover's own `--max-eta` bounds worst case; a Cancel action (kill the subprocess, no partial-progress resume) is still in scope, distinct from real pause/resume |
| Vault provenance parity gap between Portunus and the JSON fallback store | Extend both explicitly, not just the primary path (§4.3) |
| Uploaded wordlist file itself is sensitive real candidate data | Never logged, deleted after the run, same discipline as every other candidates-file in this app (§4.4) |
| Reinventing the once-only-reveal mechanism instead of reusing it | Explicit decision (§4.2) to reuse the existing `secret=True`/`consume_job_result()` pattern verbatim |

## 6. Scale assessment

**Medium.** Touches `web/vault.py` (tags parameter, both backends),
`web/app.py` (new upload route + job + confirm route), a new template
reusing the existing once-only-reveal scaffolding, and `tools/
unlock_wallet.py`'s existing subprocess call (parameterized candidates
file, not restructured). No new external service, no new cracking
integration — BTCRecover is already wired in. Proceeding to a lightweight
vertical plan, no full structured outline required.
