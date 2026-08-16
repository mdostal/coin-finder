# Design Discussion: Editable Vault Entries

**Process note:** same no-live-teammates adaptation as every epic this
session. Requested directly: "saved entries have to be able to be edited
so that we can change description or something on them."

## 1. What Are We Doing?

`web/vault.py` currently only supports add / revoke -- no way to fix a
typo'd or update a stale description without deleting and re-adding the
entry (which also loses its `first_seen`-equivalent history in Portunus).

## 2. What I Found

Portunus already has exactly this: `portunus retag <name> --description
<text>` updates a reference's metadata in place, never touching the
underlying secret value at all -- the value stays exactly as stored, only
the description changes. `web/vault.py`'s existing functions
(`add_vault_entry`, `revoke_vault_entry`) don't take a `db_path` param at
all (unlike `findings.py`/`crawl_runs.py`) -- they shell out to `portunus`
directly, falling back to a local `.env` + JSON-metadata pair when
Portunus isn't installed.

## 3. My Proposed Approach

**`web/vault.py`**: new `edit_vault_entry(name, description)`. Portunus
path: `portunus retag <name> --description <description>` (same
`stdin=DEVNULL` + `PORTUNUS_TIMEOUT_SECONDS` discipline as every other
call in this file). Fallback path: update the matching entry's
`description` field in `_load_fallback_meta()`'s list and re-save.

**`web/app.py`**: new `POST /vault/edit` route -- `name` + `description`
form fields, calls `edit_vault_entry`, redirects to `/vault`.

**`web/templates/vault.html`**: each saved-entry row's description becomes
an inline edit form (text input + save button) instead of plain text --
matches the existing per-row action-form pattern already used for
Revoke/Unarchive/Watch throughout this session's other work.

## 4. Scale Assessment

**Small.** One new function, one new route, one template tweak. One story.
