# Vertical Plan: Staging Copy with Original-Path Index

Medium scope — two sequential slices, each a working state.

## Slice 1 — Auto-staging + index module

New `web/staging_index.py` (§3.3), content-hash-based staged naming
(§3.2), hooked into the 3 `record_finding()` call sites that have a real
`source_path` (§3.1). Soft storage-growth warning log. Working state:
every new finding backed by a real local file automatically gets a
durable local copy with a real index entry — the core "don't lose this
even if the original disappears" ask, even before any review UI exists.

## Slice 2 — Staged Files review + decision actions

A new "Staged Files" page listing every indexed entry with its decision
state. Keep and Re-verify as plain instant actions; Archive & Forget as
an index-only decision marker (never deletes the real original — v1 scope
limit, confirmed explicitly in the design discussion). Working state: the
full ask — you can see what's been staged, decide what to do with each
original, with the decision durably recorded.
