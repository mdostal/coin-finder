# Vertical Plan: Wordlist Cracking Review

Medium scope — two sequential slices, each a working state.

## Slice 1 — Upload + crack job + once-only reveal review

New route: select a state-3 wallet + upload a wordlist file, dispatch a
`secret=True` job wrapping `unlock_wallet.py`'s existing BTCRecover
subprocess call against the uploaded file. Review page reuses the
existing once-only secret-reveal pattern (masked by default, one client-
side toggle). No vault ingestion yet. Working state: you can run a real
crack attempt with your own wordlist against a specific locked wallet and
see the result exactly once, safely.

## Slice 2 — Confirm-to-vault with provenance

Add an explicit "Add to vault" confirm action on the review page (only
when a real password was found) that calls `add_vault_entry` with new
provenance tags (wordlist filename, method, found-at, wallet path) —
extending both the Portunus path (`--tags`) and the JSON fallback store's
schema for parity. Working state: the full ask — a confirmed crack result
flows into the vault with real metadata about how it was found, ready to
use from the existing Unlock page, without hand-retyping.
