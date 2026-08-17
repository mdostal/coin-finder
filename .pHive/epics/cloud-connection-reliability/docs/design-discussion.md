# Design Discussion: Cloud Connection Reliability

**Process note:** same no-live-teammates adaptation as every epic this
session. Urgent, direct bug report with live evidence: two Google Drive
connections that never actually finished, permanently blocking the
"mount a multi-terabyte drive and scan it" flow the user needs right now.

## 1. What Are We Doing?

Confirmed live, with the user's own screenshots plus direct inspection of
`~/.config/rclone/rclone.conf` and the actual running `rclone` process:
`create_remote()` writes a remote's config stanza to disk **before**
Google sign-in finishes, and if sign-in fails or is abandoned, that
stanza just sits there forever -- tokenless, non-functional, and
**indistinguishable from a working connection** anywhere in the UI. The
wizard's own "You have N connection(s) already set up" line was reporting
2 completely broken connections as successes. There was no way to remove,
retry, or even see that they were broken -- confirmed by grep across
`web/mounts.py`/`web/rclone_wizard.py`/every relevant template: zero
remove/status capability exists today. One of the two broken entries had
a fabricated, non-Google `client_id`/`client_secret` (`mathew.dostal-
drive` / a value that looks like a personal password) typed into the
wizard's optional "Advanced: use your own Google API credentials"
section -- Google correctly rejected it with "Error 401: invalid_client",
exactly matching the screenshot.

Manually cleaned up both broken entries as an immediate unblock (`rclone
config delete`, verified no vault entries were left behind either). This
epic is the actual fix so it doesn't happen again and so a broken
connection is something the user can see and fix themselves, not
something that needs direct file-level intervention.

## 2. What I Found

- `create_remote()` (`web/rclone_wizard.py:25`) only checks
  `result.returncode` after `rclone config create` returns -- it never
  verifies the remote actually ended up with a working OAuth token.
  `rclone config create <name> drive scope <scope>` writes the config
  section (type/scope, and client_id/client_secret if given) to
  `rclone.conf` essentially immediately, independent of whether the
  subsequent browser OAuth handshake ever completes -- confirmed by
  inspecting the two broken entries directly (both have `type`/`scope`,
  neither has a `token` field).
- `list_remotes()` (`web/mounts.py`) is `rclone listremotes` -- a flat
  list of names, with zero concept of "did this one actually finish
  setting up." `wizard_cloud.html`/`mounts.html` both render this list
  directly as if every name means "ready to use."
- rclone's own default/shared Google Drive OAuth client
  (`202264815644-rt1o1c9evjaotbpbab10m83i8cnjk077.apps.googleusercontent.com`,
  confirmed present in the installed rclone v1.75.0 binary via `strings`)
  is the real, long-standing, actively-used-by-the-whole-rclone-userbase
  default -- not itself broken. The `invalid_client` error the user hit
  was specifically for the connection that had a **fabricated** custom
  client_id, not the one using this real default. This matters for the
  fix: the recommended, default path (no custom credentials) is already
  the reliable one -- the bug is entirely about (a) no verification/
  cleanup on failure and (b) the optional custom-credentials field
  accepting obviously-invalid input silently.
- No `remove_remote()`/status function exists anywhere in
  `web/mounts.py` or `web/rclone_wizard.py`.

## 3. My Proposed Approach

**Story ccr-01 -- verify before declaring success, clean up on
failure:** `create_remote()` gains a real post-creation check: after
`rclone config create` returns, confirm the resulting remote actually
works by running a real, cheap read call against it (`rclone lsd
<remote>: --max-depth 1` with a short timeout -- the same "did this
credential actually work" proof the mounts page will rely on, not a
config-file text check that a differently-shaped future rclone version
could silently break). On any failure path (nonzero exit, OR exit 0 but
the verification read fails), **delete the partial stanza**
(`rclone config delete <name>`) before returning -- a failed attempt
must never leave the config file dirty. The reported error should be
specific: a custom client_id that doesn't look like a real Google OAuth
client (doesn't end in `.apps.googleusercontent.com`) is caught and
reported **before** even attempting the OAuth flow, not five minutes
later as a Google error page -- exactly the mistake that produced the
first broken entry.

**Story ccr-02 -- "just hit sign in" as the actual primary path, plus
remove/retry:** The wizard's default, one-click flow (no custom
credentials, rclone's real shared client) becomes the clearly-primary
action -- the "Advanced: use your own Google API credentials" section
gets stronger framing that it is NOT needed for this to work (most users
should never open it), reducing the exact confusion that produced the
fabricated-credentials entry. `list_remotes()`-based UI everywhere gains
a real status check (reusing ccr-01's verification call, cached briefly
since it's a real network call) so a broken/never-finished connection
displays as clearly broken, not silently listed as success. New "Remove"
action (`web/mounts.py`'s new `remove_remote()`, wired to a new route) on
both `wizard_cloud.html` and `mounts.html` so a broken or unwanted
connection can be deleted and retried from the UI -- no more needing
direct file-system intervention to recover from a failed attempt.

## 4. What This Does NOT Change

- `mount()`/`unmount()`/`is_mounted()`/`list_mounts()` -- untouched,
  these already work correctly on top of whatever `list_remotes()`
  reports; the bug is entirely upstream of them (bad data going in).
- The vault (Portunus) integration for custom client secrets -- reused
  exactly as-is; nothing about vault storage was the problem here (this
  particular broken entry's secret never actually made it into the vault
  at all, confirmed by direct inspection).
- rclone's own default shared OAuth client -- not itself broken, not
  something this project can or should try to "fix"; the fix is entirely
  about this app's own handling of success/failure around it.

## 5. Risks

- **The verification call (`rclone lsd`) is itself a real network call**
  against the user's actual Drive -- kept fast and minimal
  (`--max-depth 1`, short timeout) since it only needs to prove
  "credentials work," not enumerate anything.
- **Deleting a config stanza is destructive to rclone's own state file**
  -- scoped tightly to only the stanza `create_remote()` itself just
  created moments earlier on a verified-failed attempt, never touching
  any other remote, and only ever via `rclone config delete`, the same
  standard tool a user would use themselves.
- **This does not, and cannot, fix a case where Google itself is
  down/rate-limiting** -- that's surfaced as a clear, specific error
  (the verification step's own failure message), not silently absorbed.

## 6. Scale Assessment

**Medium.** Two stories: verify-and-cleanup on the create path (ccr-01),
then real status display + a remove/retry UI action (ccr-02). Both
touch real, already-broken user state directly -- extra care in testing
given that, same discipline as every stakes-sensitive epic this session.
