import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.search import WALLET_EXTENSIONS, WALLET_KEYWORDS, MAX_FILE_SIZE, MIN_FILE_SIZE, COIN_NAMES
from tools.checkpoint_store import CheckpointStore

CHECKPOINT_EVERY_DIRS = 200
CHECKPOINT_EVERY_SECONDS = 20
PROGRESS_EVERY_SECONDS = 0.5


def _is_excluded(candidate_path, excludes):
    """
    True if candidate_path is one of excludes, or nested under one --
    matched on real path components (via Path.parts), not a naive string
    prefix, so an exclude of "/Volumes/Old" never accidentally also
    matches "/Volumes/OldDrive2".
    """
    candidate_parts = Path(candidate_path).parts
    for excluded in excludes:
        excluded_parts = Path(excluded).parts
        if candidate_parts[: len(excluded_parts)] == excluded_parts:
            return True
    return False


def _open_checkpoint_store(checkpoint_path, start_path):
    """
    Opens (creating if absent) the sqlite-backed completed-directories
    checkpoint at checkpoint_path, or returns None if checkpoint_path is
    falsy. Backed by tools.checkpoint_store.CheckpointStore -- see that
    module's docstring for the real production OOM this design fixes
    (confirmed live on a real multi-terabyte Google Drive mount: 34,199
    directories in, an in-memory-set-to-JSON checkpoint was already a
    3.85MB file fully re-sorted and rewritten every ~20 seconds, with
    memory growing without bound for the life of the scan).

    units_table="completed_dirs"/unit_column="path" reproduce this
    module's exact already-shipped schema byte-for-byte (rather than the
    store's generic default), so web/app.py's raw-sqlite interrupted-scan
    reads and any leftover checkpoint file from before this extraction
    keep working unmodified.

    A checkpoint recorded against a DIFFERENT start_path (an unrelated
    scan's leftover file re-used at the same path) is treated as stale:
    its completed_dirs rows are wiped and the file is reused fresh,
    rather than left on disk unread -- there is exactly one scan per
    checkpoint_path in practice (see web/app.py's _find_checkpoint_path),
    so this only ever fires on a genuinely stale leftover.
    """
    if not checkpoint_path:
        return None
    return CheckpointStore(
        checkpoint_path,
        run_key={"start_path": str(start_path)},
        units_table="completed_dirs",
        unit_column="path",
    )


def search_for_wallets(start_path, output_file, checkpoint_path=None, progress_callback=None, excludes=None):
    """
    Walks start_path looking for likely wallet files. A long walk over a
    huge mounted drive is exactly the kind of job that used to be thrown
    away entirely by an app quit/update/crash mid-scan -- os.walk had no
    notion of "already checked this directory," so any interruption meant
    starting over from nothing.

    checkpoint_path, when given, makes this resumable via a small sqlite
    db (see _open_checkpoint_store) recording exactly which directories are
    already done: after every CHECKPOINT_EVERY_DIRS directories (or
    CHECKPOINT_EVERY_SECONDS, whichever comes first), directories
    completed since the last flush are committed and output_file is
    flushed. If checkpoint_path already has completed directories
    recorded for this exact start_path, those are skipped this run
    instead of being re-walked -- picking back up close to where a prior,
    interrupted run left off instead of restarting from zero. The
    checkpoint is removed once the walk finishes cleanly. output_file
    itself is opened in append mode when resuming (its prior matches are
    real results, not stale data) and truncated fresh otherwise.

    :param progress_callback: optional callable(current, total, message).
        total is always None here -- there is no way to know how many
        directories a walk will visit before it's done, so this reports
        real, live movement (directories walked, matches found so far,
        current path) rather than a fabricated percentage. Throttled to
        roughly every PROGRESS_EVERY_SECONDS so a fast walk over small
        directories doesn't flood the caller.
    :param excludes: optional list of paths -- user-configurable (see
        web/scan_excludes.py), never a built-in blocklist. A directory
        that is one of these, or nested under one, is skipped entirely
        (pruned from os.walk, not just excluded from the results) --
        the actual point being to avoid both wasted time AND false-
        positive matches from paths already known not to matter.
    """
    if progress_callback is None:
        progress_callback = lambda current, total, message="": None
    excludes = excludes or []

    store = _open_checkpoint_store(checkpoint_path, start_path)
    dirs_walked = store.count_completed() if store else 0
    resuming = dirs_walked > 0

    potential_wallets = []
    if resuming and Path(output_file).exists():
        potential_wallets = [line.rstrip("\n") for line in open(output_file) if line.strip()]
        print(f"Resuming scan of {start_path}: {dirs_walked} directory(ies) already checked, {len(potential_wallets)} wallet(s) found so far.")

    out_f = open(output_file, "a" if resuming else "w")

    def _flush():
        out_f.flush()
        if store:
            store.flush()

    dirs_since_checkpoint = 0
    last_checkpoint_at = time.time()
    last_progress_at = time.time()

    for root, dirs, files in os.walk(start_path):
        if excludes and _is_excluded(root, excludes):
            dirs[:] = []  # don't descend into an excluded subtree at all
            continue

        if excludes:
            dirs[:] = [d for d in dirs if not _is_excluded(str(Path(root) / d), excludes)]

        if store and store.is_completed(root):
            continue

        for file in files:
            file_path = Path(root) / file
            try:
                file_size = file_path.stat().st_size

                # Skip files outside the size range
                if file_size > MAX_FILE_SIZE:
                    print(f"Skipping large file: {file_path} ({file_size / (1024 * 1024):.2f} MB)")
                    continue
                if file_size < MIN_FILE_SIZE:
                    print(f"Skipping empty or very small file: {file_path}")
                    continue

                # Check if the file matches extensions or keywords
                if any(file_path.suffix.lower() == ext for ext in WALLET_EXTENSIONS) or \
                   any(coin_name in file.lower() for coin_name in COIN_NAMES) or \
                   any(keyword in file.lower() for keyword in WALLET_KEYWORDS):
                    potential_wallets.append(str(file_path))
                    out_f.write(str(file_path) + "\n")
            except Exception as e:
                print(f"Error accessing file {file_path}: {e}")

        if store:
            store.mark_completed(root)
        dirs_since_checkpoint += 1
        dirs_walked += 1
        if store and (dirs_since_checkpoint >= CHECKPOINT_EVERY_DIRS or time.time() - last_checkpoint_at >= CHECKPOINT_EVERY_SECONDS):
            _flush()
            dirs_since_checkpoint = 0
            last_checkpoint_at = time.time()

        if time.time() - last_progress_at >= PROGRESS_EVERY_SECONDS:
            progress_callback(dirs_walked, None, f"{len(potential_wallets)} potential wallet(s) found so far — {root}")
            last_progress_at = time.time()

    progress_callback(dirs_walked, None, f"{len(potential_wallets)} potential wallet(s) found — walk complete")
    _flush()
    out_f.close()
    if store:
        store.delete()

    print(f"Search complete. Found {len(potential_wallets)} potential wallet files.")
    print(f"Results saved to {output_file}.")
    return potential_wallets

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Search for potential crypto wallet files.")
    parser.add_argument("start_path", help="Path to start searching from.")
    parser.add_argument("output_file", help="File to save the list of wallet files.")
    args = parser.parse_args()

    search_for_wallets(args.start_path, args.output_file)
