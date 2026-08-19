# Vertical Plan: Password / Note Scanner

Medium scope — two sequential slices, each a working state.

## Slice 1 — Core scanner + review UI (no vault ingestion yet)

New `tools/find_password_candidates.py`, built on `find_seed_phrases.py`'s
file-discovery shape (§3.1 of the design discussion) with the keyword-
proximity heuristic (§3.2), scoped to plain text per §3.3. New web job
type + route showing discovered candidates (label context, source file,
line) for the user to review. Working state: you can run a scan and see
what it found, with real numbers on volume/plausible false positives,
before anything touches the vault.

## Slice 2 — Confirm-and-ingest to vault

A confirm step (select which reviewed candidates to actually add) that
loops `add_vault_entry` with deterministic, collision-safe naming (§3.4),
never auto-ingesting silently. Working state: the full ask — discovered
candidates flow into the same vault/auto-unlock pipeline every other
credential in this app already uses, with a human confirming what
actually gets added.
