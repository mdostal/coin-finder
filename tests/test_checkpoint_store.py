import sqlite3
import threading
import time

import pytest

from tools.checkpoint_store import CheckpointStore


def test_mark_completed_then_is_completed_true_after_flush(tmp_path):
    store = CheckpointStore(tmp_path / "cp.db", run_key={"start_path": "/a"})

    store.mark_completed("/a/one")
    store.flush()

    assert store.is_completed("/a/one") is True
    assert store.is_completed("/a/two") is False


def test_is_completed_true_before_flush_too(tmp_path):
    """A unit marked completed is considered done immediately, even before
    the next flush -- callers must never re-dispatch/re-process a unit
    just because it hasn't hit disk yet."""
    store = CheckpointStore(tmp_path / "cp.db", run_key={"start_path": "/a"})

    store.mark_completed("/a/one")

    assert store.is_completed("/a/one") is True


def test_count_completed_reflects_committed_units(tmp_path):
    store = CheckpointStore(tmp_path / "cp.db", run_key={"start_path": "/a"})

    assert store.count_completed() == 0

    store.mark_completed("/a/one")
    store.mark_completed("/a/two")
    store.flush()

    assert store.count_completed() == 2


def test_resume_reopens_store_with_same_run_key_and_sees_prior_completions(tmp_path):
    checkpoint_path = tmp_path / "cp.db"
    store = CheckpointStore(checkpoint_path, run_key={"start_path": "/a"})
    store.mark_completed("/a/one")
    store.flush()
    store.close()

    resumed = CheckpointStore(checkpoint_path, run_key={"start_path": "/a"})

    assert resumed.is_completed("/a/one") is True
    assert resumed.count_completed() == 1


def test_run_key_mismatch_resets_completed_units(tmp_path):
    """A checkpoint recorded against a different run (e.g. a different
    start_path/input_file) is stale -- its completed units are wiped
    rather than incorrectly reused, mirroring tonight's already-shipped
    search-checkpoint behavior."""
    checkpoint_path = tmp_path / "cp.db"
    store = CheckpointStore(checkpoint_path, run_key={"start_path": "/a"})
    store.mark_completed("/a/one")
    store.flush()
    store.close()

    reopened = CheckpointStore(checkpoint_path, run_key={"start_path": "/different"})

    assert reopened.is_completed("/a/one") is False
    assert reopened.count_completed() == 0


def test_fresh_checkpoint_path_starts_with_nothing_completed(tmp_path):
    store = CheckpointStore(tmp_path / "cp.db", run_key={"input_file": "/x/search_output.txt"})

    assert store.count_completed() == 0
    assert store.is_completed("/x/one.dat") is False


def test_is_paused_defaults_to_false(tmp_path):
    store = CheckpointStore(tmp_path / "cp.db", run_key={"start_path": "/a"})

    assert store.is_paused() is False


def test_request_pause_then_is_paused_true(tmp_path):
    store = CheckpointStore(tmp_path / "cp.db", run_key={"start_path": "/a"})

    store.request_pause()

    assert store.is_paused() is True


def test_clear_pause_resets_to_not_paused(tmp_path):
    store = CheckpointStore(tmp_path / "cp.db", run_key={"start_path": "/a"})
    store.request_pause()

    store.clear_pause()

    assert store.is_paused() is False


def test_request_pause_is_visible_from_a_second_connection_to_the_same_file(tmp_path):
    """The real use case (§1.5): a pause route opens its own CheckpointStore
    against the same checkpoint_path a running job already has open, and
    calls request_pause() -- the running job's own store must see it on
    its next is_paused() check."""
    checkpoint_path = tmp_path / "cp.db"
    running_job_store = CheckpointStore(checkpoint_path, run_key={"start_path": "/a"})
    pause_route_store = CheckpointStore(checkpoint_path, run_key={"start_path": "/a"})

    pause_route_store.request_pause()

    assert running_job_store.is_paused() is True


def test_delete_removes_the_checkpoint_file(tmp_path):
    checkpoint_path = tmp_path / "cp.db"
    store = CheckpointStore(checkpoint_path, run_key={"start_path": "/a"})
    store.mark_completed("/a/one")
    store.flush()

    store.delete()

    assert not checkpoint_path.exists()


def test_wal_mode_is_configured(tmp_path):
    store = CheckpointStore(tmp_path / "cp.db", run_key={"start_path": "/a"})

    mode = store.conn.execute("PRAGMA journal_mode").fetchone()[0]

    assert mode.lower() == "wal"


def test_busy_timeout_is_configured(tmp_path):
    store = CheckpointStore(tmp_path / "cp.db", run_key={"start_path": "/a"})

    timeout_ms = store.conn.execute("PRAGMA busy_timeout").fetchone()[0]

    assert timeout_ms > 0


def test_custom_table_and_column_names_are_used(tmp_path):
    """search_wallets.py needs the extracted store to reproduce its exact
    already-shipped schema (table `completed_dirs`, column `path`) so
    web/app.py's raw-sqlite interrupted-scan reads (and any leftover
    checkpoint files from before this refactor) keep working unmodified."""
    checkpoint_path = tmp_path / "cp.db"
    store = CheckpointStore(
        checkpoint_path,
        run_key={"start_path": "/a"},
        units_table="completed_dirs",
        unit_column="path",
    )
    store.mark_completed("/a/one")
    store.flush()
    store.close()

    conn = sqlite3.connect(str(checkpoint_path))
    assert conn.execute("SELECT path FROM completed_dirs").fetchall() == [("/a/one",)]
    assert conn.execute("SELECT value FROM meta WHERE key = 'start_path'").fetchone() == ("/a",)
    conn.close()


def test_opening_a_legacy_search_checkpoint_file_is_understood(tmp_path):
    """A checkpoint file written by the pre-extraction inline
    _open_checkpoint_db helper (or by search_wallets.py's own test suite,
    which writes this exact raw schema) must resume correctly through the
    new store -- proves the extraction is genuinely byte-for-byte
    schema-compatible, not just behaviorally similar."""
    checkpoint_path = tmp_path / "cp.db"
    conn = sqlite3.connect(str(checkpoint_path))
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE completed_dirs (path TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO meta (key, value) VALUES ('start_path', ?)", ("/a",))
    conn.executemany("INSERT INTO completed_dirs (path) VALUES (?)", [("/a/one",), ("/a/two",)])
    conn.commit()
    conn.close()

    store = CheckpointStore(
        checkpoint_path,
        run_key={"start_path": "/a"},
        units_table="completed_dirs",
        unit_column="path",
    )

    assert store.is_completed("/a/one") is True
    assert store.is_completed("/a/two") is True
    assert store.count_completed() == 2


def test_flush_cost_stays_flat_regardless_of_prior_completed_unit_count(tmp_path):
    """Regression test for tonight's real OOM incident: the original
    checkpoint design held every completed unit in memory and rewrote the
    *entire* set to disk on every flush, so flush cost grew linearly (and
    eventually catastrophically) with how much had already been done.
    This asserts flush() only ever pays for what's newly buffered since
    the last flush -- a fixed-size batch flushed after 100k prior
    completions must not be meaningfully slower than the same batch size
    flushed against an empty store.
    """
    store = CheckpointStore(tmp_path / "cp.db", run_key={"start_path": "/a"})
    batch_size = 500

    def _flush_one_batch(offset):
        for i in range(batch_size):
            store.mark_completed(f"/a/dir-{offset + i}")
        start = time.perf_counter()
        store.flush()
        return time.perf_counter() - start

    first_batch_time = _flush_one_batch(0)

    # Fast-forward: 100k+ units already committed before the timed batch.
    for offset in range(batch_size, 100_000, batch_size):
        _flush_one_batch(offset)

    late_batch_time = _flush_one_batch(100_000)

    assert store.count_completed() > 100_000

    # Generous bound (5x, not 1.05x) to absorb real machine noise -- the
    # actual bug this guards against is unbounded/linear growth (a 100k+
    # prior-count flush taking orders of magnitude longer), not minor
    # timing jitter between two runs on a real filesystem.
    assert late_batch_time < first_batch_time * 5 + 0.2


def test_mark_completed_does_not_grow_process_memory_with_a_python_side_full_set(tmp_path):
    """Guards against reintroducing the exact OOM anti-pattern: the store
    must never keep every completed unit id resident in Python memory --
    only the small since-last-flush buffer. Verified indirectly: the
    in-memory pending buffer is empty immediately after each flush,
    regardless of how many units have been completed in total."""
    store = CheckpointStore(tmp_path / "cp.db", run_key={"start_path": "/a"})

    for batch in range(5):
        for i in range(1000):
            store.mark_completed(f"/a/dir-{batch}-{i}")
        store.flush()
        assert len(store._pending) == 0

    assert store.count_completed() == 5000


def test_concurrent_is_completed_mark_completed_and_flush_from_many_threads_is_safe(tmp_path):
    """Real requirement, not a hypothetical: sse-03's search-walk thread
    pool calls is_completed/mark_completed/flush directly from worker
    threads (not just the thread that created the store), and
    check_wallet_balances' existing ThreadPoolExecutor (sse-02) already
    does the same for mark_completed/flush from inside check_one() once
    CHECKPOINT_EVERY_ADDRESSES/SECONDS trips. sqlite3 connections default
    to check_same_thread=True, so a naive store would raise
    ProgrammingError the first time any of these is called from a thread
    other than the one that opened the connection -- confirmed by direct
    reproduction before this fix. This drives many real threads at once
    and asserts zero exceptions plus an exact final count, proving the
    lock genuinely serializes access rather than just silencing errors."""
    store = CheckpointStore(tmp_path / "cp.db", run_key={"start_path": "/a"})
    n_threads = 8
    per_thread = 100
    errors = []
    errors_lock = threading.Lock()

    def worker(idx):
        try:
            for i in range(per_thread):
                unit_id = f"/a/dir-{idx}-{i}"
                if not store.is_completed(unit_id):
                    store.mark_completed(unit_id)
                if i % 10 == 0:
                    store.flush()
                store.is_paused()
        except Exception as e:
            with errors_lock:
                errors.append(e)

    threads = [threading.Thread(target=worker, args=(idx,)) for idx in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    store.flush()

    assert errors == []
    assert store.count_completed() == n_threads * per_thread
