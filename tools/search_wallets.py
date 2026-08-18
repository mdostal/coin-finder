import os
import queue
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.search import WALLET_EXTENSIONS, WALLET_KEYWORDS, MAX_FILE_SIZE, MIN_FILE_SIZE, COIN_NAMES
from tools.checkpoint_store import CheckpointPaused, CheckpointStore

CHECKPOINT_EVERY_DIRS = 200
CHECKPOINT_EVERY_SECONDS = 20
PROGRESS_EVERY_SECONDS = 0.5

# Deliberately conservative (structured-outline.md #1.4, risk R3):
# directory listing is I/O-bound, so Python threads genuinely help here
# (I/O releases the GIL) -- but this mount is already known to trip a
# shared Google Drive API quota under too much concurrent traffic (the
# real --checkers 32 -> repeated 403 RATE_LIMIT_EXCEEDED incident that
# tuned web/mounts.py's own --checkers 16/--tpslimit 8 tonight). More
# concurrent walk_threads here means more concurrent rclone API calls
# underneath, one layer below -- so this is deliberately small (2-4) and
# independently tunable from rclone's own --checkers/--tpslimit, never
# multiplied against it. A real load test against a real mounted Google
# Drive is still required before this ships to production -- not just
# passing unit tests (see search_for_wallets' walk_threads docstring).
DEFAULT_WALK_THREADS = 3

# Sentinel put on the work queue once per worker after all real work is
# drained (queue.join() returned) -- wakes each worker's blocking get()
# so it can exit cleanly instead of the pool being made of daemon
# threads nobody ever joins.
_SHUTDOWN = object()


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


def _list_one_level(directory):
    """
    Returns (dirs, files) -- the immediate (non-recursive) contents of
    directory -- by consuming exactly the first tuple os.walk(directory)
    yields and discarding the generator before it would ever recurse.
    This reuses os.walk's own, already-battle-tested error/symlink
    handling (onerror=None: a directory that can't be listed -- e.g.
    permission denied, or a dead mount mid-listing -- silently yields
    nothing, exactly like today's sequential walk, rather than raising
    and taking down a worker thread) instead of reimplementing those
    semantics by hand on top of os.scandir.
    """
    walked = next(os.walk(directory), None)
    if walked is None:
        return [], []
    _, dirs, files = walked
    return dirs, files


def _match_file(file_path, file_name):
    """
    True if file_path/file_name matches the existing wallet-file
    patterns -- extension, coin name, or keyword -- unchanged from the
    sequential walk's inline logic (extracted verbatim so both the
    matching logic itself, and the size-skip prints around it, stay
    identical to before; only the walk driver around this changed).
    """
    return (
        any(file_path.suffix.lower() == ext for ext in WALLET_EXTENSIONS)
        or any(coin_name in file_name.lower() for coin_name in COIN_NAMES)
        or any(keyword in file_name.lower() for keyword in WALLET_KEYWORDS)
    )


def search_for_wallets(
    start_path, output_file, checkpoint_path=None, progress_callback=None, excludes=None, walk_threads=DEFAULT_WALK_THREADS
):
    """
    Walks start_path looking for likely wallet files. A long walk over a
    huge mounted drive is exactly the kind of job that used to be thrown
    away entirely by an app quit/update/crash mid-scan -- os.walk had no
    notion of "already checked this directory," so any interruption meant
    starting over from nothing.

    Directory listing is I/O-bound (unlike CPU-bound work, Python threads
    genuinely parallelize this -- I/O releases the GIL), so the walk
    itself is driven by a small, bounded pool of walk_threads worker
    threads pulling from a shared work queue (seeded with start_path):
    each worker claims a not-yet-completed directory, lists exactly that
    one level, matches its files against the existing patterns unchanged,
    and pushes any subdirectories back onto the queue for any worker
    (including itself) to pick up next. checkpoint_path's CheckpointStore
    is what lets multiple workers coordinate safely on "is this directory
    already done" -- see tools.checkpoint_store.CheckpointStore, which is
    itself internally lock-serialized so it's safe to call from any
    worker thread, not just the one that opened it.

    :param walk_threads: how many directories can be listed concurrently.
        Defaults to DEFAULT_WALK_THREADS (2-4, deliberately conservative)
        -- more concurrent Python-side directory reads against a mounted
        Google Drive means more concurrent rclone API calls one layer
        below this, which is exactly what tripped a real shared-quota
        incident with a different concurrency knob (--checkers 32,
        confirmed live -- see web/mounts.py's mount() docstring) tonight.
        Deliberately independent of rclone's own --checkers/--tpslimit
        tuning -- this is a separate knob, never multiplied against that
        one. IMPORTANT: this default has only been unit-tested against a
        local filesystem so far; a real load test against a real mounted
        Google Drive (watching its mount log for new 403
        RATE_LIMIT_EXCEEDED errors versus today's --checkers 16/
        --tpslimit 8 baseline) is a hard requirement before this ships to
        production, not something a test suite can verify on its own.

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
        (never queued for any worker, not just excluded from the
        results) -- the actual point being to avoid both wasted time AND
        false-positive matches from paths already known not to matter.
    """
    if progress_callback is None:
        progress_callback = lambda current, total, message="": None
    excludes = excludes or []
    walk_threads = max(1, walk_threads)

    store = _open_checkpoint_store(checkpoint_path, start_path)
    dirs_walked = store.count_completed() if store else 0
    resuming = dirs_walked > 0

    potential_wallets = []
    if resuming and Path(output_file).exists():
        potential_wallets = [line.rstrip("\n") for line in open(output_file) if line.strip()]
        print(f"Resuming scan of {start_path}: {dirs_walked} directory(ies) already checked, {len(potential_wallets)} wallet(s) found so far.")

    out_f = open(output_file, "a" if resuming else "w")

    # Guards out_f + potential_wallets together -- a match is only ever
    # visible in one without the other, and concurrent writers can never
    # interleave/corrupt a line, satisfying the story's explicit
    # concurrent-write-safety ask with a single small, rarely-contended
    # lock (writing one line, or flushing, is fast).
    output_lock = threading.Lock()
    # Guards the walk's own bookkeeping counters (dirs_walked/
    # dirs_since_checkpoint/timestamps) -- separate from output_lock so a
    # counter update never has to wait on a slower output flush.
    state_lock = threading.Lock()

    def _flush():
        with output_lock:
            out_f.flush()
            if store:
                store.flush()

    state = {
        "dirs_walked": dirs_walked,
        "dirs_since_checkpoint": 0,
        "last_checkpoint_at": time.time(),
        "last_progress_at": time.time(),
    }

    work_queue = queue.Queue()
    work_queue.put(str(start_path))

    errors = []
    errors_lock = threading.Lock()

    # sse-04: set only from inside the need_flush block below, right after
    # a flush has already durably committed progress -- so by the time any
    # worker observes this set, there is nothing left in flight that a
    # pause could interrupt mid-write. Checked at the top of
    # _process_directory so an item already queued (but not yet started)
    # is simply skipped rather than processed -- it was never marked
    # completed nor removed from the queue's future candidates, so a
    # resumed run rediscovers it naturally by walking from start_path
    # again, identical to how a hard crash mid-walk already behaves today.
    paused_event = threading.Event()

    def _process_directory(root):
        if paused_event.is_set():
            return
        if excludes and _is_excluded(root, excludes):
            return  # never queued further -- whole subtree pruned, same as the sequential walk's dirs[:] = []

        dirs, files = _list_one_level(root)
        if excludes:
            dirs = [d for d in dirs if not _is_excluded(str(Path(root) / d), excludes)]
        for d in dirs:
            work_queue.put(str(Path(root) / d))

        # A directory already marked completed (by this or an earlier
        # run) still has its subdirectories queued above -- exactly like
        # the sequential walk, which always continues descending into
        # `dirs` regardless of whether `root` itself gets re-processed --
        # but its own files are never re-matched/re-written.
        if store and store.is_completed(root):
            return

        matches = []
        for file in files:
            file_path = Path(root) / file
            try:
                file_size = file_path.stat().st_size

                if file_size > MAX_FILE_SIZE:
                    print(f"Skipping large file: {file_path} ({file_size / (1024 * 1024):.2f} MB)")
                    continue
                if file_size < MIN_FILE_SIZE:
                    print(f"Skipping empty or very small file: {file_path}")
                    continue

                if _match_file(file_path, file):
                    matches.append(str(file_path))
            except Exception as e:
                print(f"Error accessing file {file_path}: {e}")

        if matches:
            with output_lock:
                for match in matches:
                    potential_wallets.append(match)
                    out_f.write(match + "\n")

        if store:
            store.mark_completed(root)

        need_flush = False
        need_progress = False
        with state_lock:
            state["dirs_since_checkpoint"] += 1
            state["dirs_walked"] += 1
            if store and (
                state["dirs_since_checkpoint"] >= CHECKPOINT_EVERY_DIRS
                or time.time() - state["last_checkpoint_at"] >= CHECKPOINT_EVERY_SECONDS
            ):
                need_flush = True
                state["dirs_since_checkpoint"] = 0
                state["last_checkpoint_at"] = time.time()
            if time.time() - state["last_progress_at"] >= PROGRESS_EVERY_SECONDS:
                need_progress = True
                state["last_progress_at"] = time.time()
            dirs_walked_snapshot = state["dirs_walked"]

        if need_flush:
            _flush()
            # Checked at the same point the checkpoint is already flushed
            # (sse-04: "no new polling loop") -- request_pause() is durable
            # and immediately visible to this store's own connection, even
            # though it was set by a completely different connection (the
            # pause route's, opened against this same checkpoint file).
            if store and store.is_paused():
                paused_event.set()
        if need_progress:
            with output_lock:
                wallets_so_far = len(potential_wallets)
            progress_callback(dirs_walked_snapshot, None, f"{wallets_so_far} potential wallet(s) found so far — {root}")

    def _worker():
        while True:
            item = work_queue.get()
            try:
                if item is _SHUTDOWN:
                    return
                _process_directory(item)
            except Exception as e:
                with errors_lock:
                    errors.append(e)
            finally:
                work_queue.task_done()

    threads = [threading.Thread(target=_worker, daemon=True) for _ in range(walk_threads)]
    for t in threads:
        t.start()

    # Blocks until every item ever put() (including subdirectories
    # queued by workers while processing) has had task_done() called --
    # the standard, correct way to know a dynamically-growing queue like
    # this one has been fully drained.
    work_queue.join()

    for _ in threads:
        work_queue.put(_SHUTDOWN)
    for t in threads:
        t.join()

    if errors:
        raise errors[0]

    _flush()
    out_f.close()

    if paused_event.is_set():
        # Never delete the checkpoint on a pause -- there IS something
        # left to resume, unlike clean completion. output_file already
        # holds every real match found so far (written incrementally as
        # each directory was processed, not buffered until the end), so
        # nothing found before the pause is lost.
        print(f"Search paused. Found {len(potential_wallets)} potential wallet file(s) so far.")
        raise CheckpointPaused(f"search paused after {state['dirs_walked']} directories")

    progress_callback(state["dirs_walked"], None, f"{len(potential_wallets)} potential wallet(s) found — walk complete")
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
