# Design Discussion: nfsmount Fix

**Process note:** same no-live-teammates adaptation as every epic this
session. Discovered live, immediately after `cloud-connection-
reliability` shipped and the user successfully reconnected Google
Drive for the first time: the resulting mount attempt failed with
health "ERROR" and zero diagnostic information anywhere in the UI.

## 1. What Are We Doing?

`web/mounts.py`'s `mount()` runs `rclone mount ...` -- confirmed live via
direct reproduction (ran the exact command by hand) that this is not a
one-off environment issue but a **fundamental, structural bug**:
Homebrew's macOS build of rclone does not include FUSE support at all.
`brew info rclone`'s own caveat says so directly: "Homebrew's
installation does not include the `mount` subcommand on macOS which
depends on FUSE, use `nfsmount` instead." Every user who installs rclone
through this app's own guided installer (`install_rclone()`, itself a
`brew install rclone` call) gets a binary that can never successfully
mount anything -- this affects 100% of macOS users of this feature, not
just this one instance.

## 2. What I Found

- Direct reproduction: `rclone mount "Dostal Drive:" /tmp/... --read-only
  --vfs-cache-mode minimal` fails immediately with `CRITICAL: Fatal
  error: failed to mount FUSE fs: rclone mount is not supported on MacOS
  when rclone is installed via Homebrew.`
- `rclone nfsmount "Dostal Drive:" /tmp/... --read-only --vfs-cache-mode
  minimal` (same flags, different subcommand) **works** -- verified live,
  the real Google Drive's actual file listing came back through the NFS
  mount within a few seconds, no macFUSE/system-extension approval
  needed at all (NFS mounting is a macOS-native mechanism, not a
  third-party kernel extension).
- `web/mounts.py`'s `mount()` discards all subprocess output
  (`stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL`) -- confirmed
  this is why the failure showed as a bare "ERROR" pill with zero
  diagnostic information anywhere in the UI. The CRITICAL error message
  rclone actually produces (which names the exact problem and even
  suggests the fix) was being thrown away.
- `unmount()`'s plain `umount <mount_point>` already works unmodified
  for either mount mechanism -- `umount` is a generic macOS command, not
  FUSE-specific.

## 3. My Proposed Approach

Two changes, both small and surgical:

1. `mount()`: `rclone mount` -> `rclone nfsmount`, otherwise identical
   (same flags, same read-only guarantee, same background-process
   tracking). No macFUSE dependency, no system-extension approval
   friction -- confirmed live this removes an entire class of first-run
   pain the current `install_rclone()` flow already warns users to
   expect (a warning that becomes unnecessary once mounting doesn't need
   macFUSE at all).
2. Capture real diagnostics instead of discarding them: `mount()`
   redirects stderr to a real log file (next to the tracked mount state,
   e.g. `<mount_point>.rclone.log` or a per-remote log path under
   `app_data_dir()`) instead of `DEVNULL`. `list_mounts()`/the mounts
   page surfaces the last few lines of that log when health is "ERROR"
   -- turning a bare, undiagnosable "ERROR" pill into something a user
   can actually act on next time (even though THIS specific failure mode
   is now fixed by the nfsmount switch itself).

## 4. What This Does NOT Change

- `unmount()`, `is_mounted()`, `list_mounts()`'s health-check logic --
  untouched, already mechanism-agnostic.
- `install_rclone()` -- still `brew install rclone` (Homebrew's rclone
  binary DOES include `nfsmount`, just not `mount` -- confirmed via the
  same `brew info` caveat, which explicitly names `nfsmount` as the
  working alternative). No new install mechanism needed.
- The wizard/`create_remote()` (`web/rclone_wizard.py`) -- untouched,
  unrelated to this (that already works, confirmed live: "Dostal Drive"
  shows "connected").

## 5. Risks

- **NFS mount characteristics differ subtly from FUSE** (e.g. some
  edge-case file operations, latency profile) -- acceptable for this
  app's actual use (read-only scanning of file contents), and it's the
  only mechanism that works at all via Homebrew's rclone on macOS, so
  there's no working FUSE alternative to weigh it against.
- **Log file growth** -- one small log per mount attempt, not unbounded;
  same order of magnitude as other per-run artifacts this app already
  produces (scan output directories, etc).

## 6. Scale Assessment

**Tiny, single story.** One subcommand swap + basic diagnostic capture.
Verified against the real, live failure before writing any epic
scaffolding -- this is about as concrete as a bug report gets.
