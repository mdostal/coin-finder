# Design Discussion: Google Drive Adapter

**Process note:** same no-live-teammates adaptation as prior epics. This one
included a real, immediately actionable finding during research, and a
mid-flight safety correction.

## 1. What Are We Doing?

User asked for an adapter to "slow crawl" Google Drive backups, alongside
local hard drives. A quick metadata-only search using this session's
already-connected Google Drive tools immediately found real candidates:
`diamond backup wallet.dat` (64KB), `helium-wallet` (11MB), and a Google Doc
literally titled "Circles wallet."

## 2. A real safety correction, made mid-session

Reading the "Circles wallet" doc's content via the connected tool pulled a
real, live 24-word phrase into this session's own context/transcript --
exactly the class of online-secret-exposure the BTCRecover `SKILL.md`
warned about (see `btcrecover-integration` epic), just via a door I hadn't
been guarding: **any content retrieved through the connected Drive tools
necessarily passes through the AI model's context before it can be saved
anywhere**, unlike local `Bash`/`Write` operations where a file moves
disk-to-disk without an LLM touching its bytes. Downloading `diamond backup
wallet.dat` or `helium-wallet` the same way would have had the identical
problem (private key material flowing through context).

**Correction applied:** metadata search (filenames/sizes/folders) via the
connected tools stays fine -- it's the same class of read as `ls`. Anything
that might contain secrets (file *content*, document *text*) now goes
through this epic's own standalone tool instead, using the user's own
Google OAuth credentials, running as a local Python process where content
flows Drive-server -> local disk directly, the same architecture as every
other tool built this session. Neither downloaded file was fetched through
the connected tools once this was recognized; the user was pointed at the
seed-phrase doc directly (its own Drive link) instead of being shown the
words.

## 3. Approach

1. **New dependencies**: `google-api-python-client`, `google-auth-httplib2`,
   `google-auth-oauthlib` -- Google's own official client libraries (the
   audited-library principle, applied to Drive API access the same way it
   was applied to crypto operations).
2. **`tools/scan_google_drive.py`**:
   - `is_wallet_like_filename(filename)` -- reuses `config/search.py`'s
     existing `WALLET_EXTENSIONS`/`WALLET_KEYWORDS`/`COIN_NAMES` (no
     duplicated heuristic).
   - `get_drive_service(credentials_path, token_path)` -- standard
     "installed app" OAuth flow (browser consent once, cached token after).
     Requires the user's own Google Cloud OAuth client credentials --
     this project cannot create those on the user's behalf; README
     documents the setup steps.
   - `list_wallet_like_files(service, query=None, page_delay_seconds=1)` --
     paginated, rate-limited ("slow crawl") metadata listing, filtered by
     name/size. Skips native Google Docs/Sheets/Slides (not downloadable
     files in the same sense -- a doc with wallet notes should be reviewed
     directly in Drive by the user, not auto-downloaded and parsed blindly).
   - `download_file(service, file_id, destination_path)` -- writes directly
     to local disk via the Drive API's media download.
   - `scan_drive_for_wallets(service, output_dir, query=None)` -- lists +
     downloads, returns a manifest. **Does not read or interpret file
     content itself** -- the existing local tools
     (`search_wallets.py`/`find_seed_phrases.py`/`scan_wallet_dat.py`) run
     against the output directory afterward, exactly like any local drive.

## 4. What Could Go Wrong

- **critical** (already happened once, corrected) -- routing secret content
  through the connected session tools. Mitigated by the architecture
  decision in Section 2: this tool never uses those connected tools for
  content, only ever local OAuth + direct-to-disk download.
- **medium** -- native Google Docs (like "Circles wallet") aren't
  auto-downloaded or scanned by this tool at all -- a real, stated gap. The
  Drive API doesn't offer symmetric raw-content download for Google's
  native formats the way it does for regular files; handling that properly
  (export-and-scan) is a reasonable, separately-scoped follow-up, not
  attempted here given the safety-sensitivity just discovered.
- **low** -- OAuth setup is real work for the user (Google Cloud project,
  enabling the Drive API, creating OAuth credentials). Documented step by
  step in README; not something this tool can complete automatically.

## 5. Verification Strategy

```
VERIFICATION PLAN:
  Tools: pytest
  Automated: is_wallet_like_filename(), list_wallet_like_files() (mocked
    Drive API service object -- pagination, name/size filtering, native-doc
    skipping), download_file() (mocked MediaIoBaseDownload), and
    scan_drive_for_wallets() (mocked, manifest shape)
  Manual: real metadata search performed live during research via the
    session's connected Drive tools (safe -- filenames/sizes only), which is
    what surfaced the real findings this epic exists to make actionable
  Not verifying: the real OAuth flow or a real download (no test credentials
    available in this environment; the user completes real setup themselves)
```

## 6. Scale Assessment

```
SCALE ASSESSMENT:
  Files affected: ~3 (new tools/scan_google_drive.py, new
    tests/test_scan_google_drive.py, requirements.txt + README.md edits) +
    tests/test_cli_standalone_invocation.py extended
  RECOMMENDATION: Proceed to a single story
```
