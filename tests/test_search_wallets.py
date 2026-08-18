import sqlite3

from tools.search_wallets import DEFAULT_WALK_THREADS, search_for_wallets


def _write_checkpoint_db(checkpoint_path, start_path, completed_dirs):
    conn = sqlite3.connect(str(checkpoint_path))
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE completed_dirs (path TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO meta (key, value) VALUES ('start_path', ?)", (str(start_path),))
    conn.executemany("INSERT INTO completed_dirs (path) VALUES (?)", [(d,) for d in completed_dirs])
    conn.commit()
    conn.close()


def test_search_for_wallets_without_checkpoint_finds_wallet_files(tmp_path):
    (tmp_path / "wallet.dat").write_bytes(b"x" * 100)
    output_file = tmp_path / "out.txt"

    results = search_for_wallets(str(tmp_path), str(output_file))

    assert str(tmp_path / "wallet.dat") in results


def test_search_for_wallets_deletes_checkpoint_on_clean_completion(tmp_path):
    (tmp_path / "wallet.dat").write_bytes(b"x" * 100)
    output_file = tmp_path / "out.txt"
    checkpoint_path = tmp_path / "checkpoint.json"

    search_for_wallets(str(tmp_path), str(output_file), checkpoint_path=str(checkpoint_path))

    assert not checkpoint_path.exists()


def test_search_for_wallets_resumes_by_skipping_already_completed_directories(tmp_path):
    """
    Regression test for the real, repeated ask: an app quit/update mid-scan
    should not throw away hours of progress. search_for_wallets can't
    naturally trigger its own CHECKPOINT_EVERY_DIRS/SECONDS thresholds in a
    small, fast test, so this writes a checkpoint db directly -- simulating
    an interrupted prior run that had already fully walked `subdir`.
    """
    subdir = tmp_path / "already-scanned"
    subdir.mkdir()
    wallet_in_subdir = subdir / "wallet.dat"
    wallet_in_subdir.write_bytes(b"x" * 100)

    output_file = tmp_path / "out.txt"
    output_file.write_text(str(wallet_in_subdir) + "\n")
    checkpoint_path = tmp_path / "checkpoint.db"
    _write_checkpoint_db(checkpoint_path, tmp_path, [str(subdir)])

    # Proves the resumed run actually SKIPS re-walking `subdir` (not just
    # coincidentally re-finding the same file): delete it from disk -- if
    # the code incorrectly re-walked `subdir`, this wallet would vanish
    # from the result instead of surviving via the checkpoint.
    wallet_in_subdir.unlink()

    new_wallet = tmp_path / "new-wallet.dat"
    new_wallet.write_bytes(b"x" * 100)

    results = search_for_wallets(str(tmp_path), str(output_file), checkpoint_path=str(checkpoint_path))

    assert str(wallet_in_subdir) in results
    assert str(new_wallet) in results
    assert not checkpoint_path.exists()
    assert str(wallet_in_subdir) in output_file.read_text()


def test_search_for_wallets_ignores_checkpoint_for_a_different_start_path(tmp_path):
    (tmp_path / "wallet.dat").write_bytes(b"x" * 100)
    output_file = tmp_path / "out.txt"
    checkpoint_path = tmp_path / "checkpoint.db"
    _write_checkpoint_db(checkpoint_path, "/some/other/path", [str(tmp_path)])

    results = search_for_wallets(str(tmp_path), str(output_file), checkpoint_path=str(checkpoint_path))

    assert str(tmp_path / "wallet.dat") in results
    assert "/some/other/path/bogus.dat" not in results


def test_search_for_wallets_reports_indeterminate_progress(tmp_path, monkeypatch):
    """
    Throttled to PROGRESS_EVERY_SECONDS in real use -- forced to 0 here so
    a fast, tiny test tree still triggers at least one callback per
    directory without needing a real wall-clock wait.
    """
    import tools.search_wallets as search_wallets_module

    monkeypatch.setattr(search_wallets_module, "PROGRESS_EVERY_SECONDS", 0)

    subdir = tmp_path / "sub"
    subdir.mkdir()
    (subdir / "wallet.dat").write_bytes(b"x" * 100)
    output_file = tmp_path / "out.txt"

    calls = []
    search_for_wallets(str(tmp_path), str(output_file), progress_callback=lambda c, t, m="": calls.append((c, t, m)))

    assert calls  # at least one progress report happened
    assert all(total is None for _, total, _ in calls)  # always indeterminate
    assert calls[-1][2].startswith("1 potential wallet(s) found")  # final call reports the real count


def test_search_for_wallets_skips_an_excluded_directory_entirely(tmp_path):
    excluded_dir = tmp_path / "junk"
    excluded_dir.mkdir()
    (excluded_dir / "wallet.dat").write_bytes(b"x" * 100)
    (tmp_path / "real_wallet.dat").write_bytes(b"x" * 100)
    output_file = tmp_path / "out.txt"

    results = search_for_wallets(str(tmp_path), str(output_file), excludes=[str(excluded_dir)])

    assert str(tmp_path / "real_wallet.dat") in results
    assert str(excluded_dir / "wallet.dat") not in results


def test_search_for_wallets_excludes_nested_subdirectories_too(tmp_path):
    excluded_dir = tmp_path / "junk"
    nested = excluded_dir / "deeper" / "still_deeper"
    nested.mkdir(parents=True)
    (nested / "wallet.dat").write_bytes(b"x" * 100)
    output_file = tmp_path / "out.txt"

    results = search_for_wallets(str(tmp_path), str(output_file), excludes=[str(excluded_dir)])

    assert results == []


def test_search_for_wallets_exclude_does_not_match_a_similarly_named_sibling(tmp_path):
    """
    Regression guard: excluding "/Volumes/Old" must not accidentally also
    exclude "/Volumes/OldDrive2" -- a naive string-prefix match would get
    this wrong; real path-component matching gets it right.
    """
    excluded_dir = tmp_path / "Old"
    excluded_dir.mkdir()
    sibling_dir = tmp_path / "OldDrive2"
    sibling_dir.mkdir()
    (sibling_dir / "wallet.dat").write_bytes(b"x" * 100)
    output_file = tmp_path / "out.txt"

    results = search_for_wallets(str(tmp_path), str(output_file), excludes=[str(excluded_dir)])

    assert str(sibling_dir / "wallet.dat") in results


def test_search_for_wallets_with_no_excludes_is_unchanged(tmp_path):
    (tmp_path / "wallet.dat").write_bytes(b"x" * 100)
    output_file = tmp_path / "out.txt"

    results = search_for_wallets(str(tmp_path), str(output_file))

    assert str(tmp_path / "wallet.dat") in results


# ---------------------------------------------------------------------------
# sse-03: parallel (thread-pool) search walk
# ---------------------------------------------------------------------------


def test_default_walk_threads_is_conservative():
    """Real, confirmed risk (structured-outline.md R3): more concurrent
    Python-side directory reads against a mounted Google Drive means more
    concurrent rclone API calls underneath -- exactly what tripped the
    shared-client quota with --checkers 32 earlier tonight. The default
    must stay small (2-4), independent of rclone's own --checkers/
    --tpslimit tuning in web/mounts.py."""
    assert 2 <= DEFAULT_WALK_THREADS <= 4


def _build_tree(root):
    """
    A moderately wide/deep tree mixing matching and non-matching files
    across several levels, used to prove parallel-walk result parity
    against the sequential walk of the same tree.

    :return: sorted list of the full paths expected to match.
    """
    expected = []
    for i in range(6):
        branch = root / f"branch{i}"
        branch.mkdir()
        wallet = branch / "wallet.dat"
        wallet.write_bytes(b"x" * 100)
        expected.append(str(wallet))

        leaf = branch / "leaf" / "deeper"
        leaf.mkdir(parents=True)
        keyfile = leaf / f"my_crypto_backup_{i}.key"
        keyfile.write_bytes(b"x" * 100)
        expected.append(str(keyfile))

        # Non-matching sibling -- must never appear in results.
        (branch / "notes.txt").write_bytes(b"just some notes")

    return sorted(expected)


def test_parallel_walk_result_parity_with_sequential_walk_of_the_same_tree(tmp_path):
    """Given a local test directory tree, when search_for_wallets runs
    with walk_threads > 1, then all files are found -- identical result
    set to the sequential (walk_threads=1) walk of the same tree."""
    tree_a = tmp_path / "a"
    tree_a.mkdir()
    expected = _build_tree(tree_a)

    sequential_results = search_for_wallets(str(tree_a), str(tmp_path / "seq_out.txt"), walk_threads=1)

    tree_b = tmp_path / "b"
    tree_b.mkdir()
    _build_tree(tree_b)
    parallel_results = search_for_wallets(str(tree_b), str(tmp_path / "par_out.txt"), walk_threads=6)

    assert sorted(sequential_results) == expected
    assert sorted(r.replace(str(tree_b), str(tree_a)) for r in parallel_results) == expected
    assert len(parallel_results) == len(expected)


def test_parallel_walk_uses_default_thread_count_and_still_finds_everything(tmp_path):
    expected = _build_tree(tmp_path)
    output_file = tmp_path / "out.txt"

    results = search_for_wallets(str(tmp_path), str(output_file))

    assert sorted(results) == expected


def test_parallel_walk_resumes_by_skipping_already_completed_directories_across_workers(tmp_path):
    """Given an interrupted parallel walk (simulated: a checkpoint db
    recording several directories as already complete, as if several
    different workers had each finished a directory before the process
    was killed), when resumed with the same checkpoint_path and
    walk_threads > 1, then already-completed directories are not
    re-walked by any worker."""
    already_done_dirs = []
    still_pending_dirs = []
    for i in range(8):
        d = tmp_path / f"dir{i}"
        d.mkdir()
        wallet = d / "wallet.dat"
        wallet.write_bytes(b"x" * 100)
        if i % 2 == 0:
            already_done_dirs.append(d)
        else:
            still_pending_dirs.append(d)

    output_file = tmp_path / "out.txt"
    # Simulate the durable output a prior, interrupted run had already
    # flushed for the directories it finished before being killed.
    output_file.write_text("".join(str(d / "wallet.dat") + "\n" for d in already_done_dirs))

    checkpoint_path = tmp_path / "checkpoint.db"
    _write_checkpoint_db(checkpoint_path, tmp_path, [str(d) for d in already_done_dirs])

    # Prove a genuine skip, not a coincidental re-find: delete the
    # "already done" wallets from disk. If any worker re-walked one of
    # these directories, its match would vanish from the result instead
    # of surviving via the checkpoint + preloaded output_file.
    for d in already_done_dirs:
        (d / "wallet.dat").unlink()

    results = search_for_wallets(
        str(tmp_path), str(output_file), checkpoint_path=str(checkpoint_path), walk_threads=4
    )

    for d in already_done_dirs:
        assert str(d / "wallet.dat") in results
    for d in still_pending_dirs:
        assert str(d / "wallet.dat") in results
    assert not checkpoint_path.exists()


def test_parallel_walk_skips_an_excluded_directory_entirely_with_multiple_workers(tmp_path):
    excluded_dir = tmp_path / "junk"
    excluded_dir.mkdir()
    (excluded_dir / "wallet.dat").write_bytes(b"x" * 100)
    (tmp_path / "real_wallet.dat").write_bytes(b"x" * 100)
    output_file = tmp_path / "out.txt"

    results = search_for_wallets(str(tmp_path), str(output_file), excludes=[str(excluded_dir)], walk_threads=4)

    assert str(tmp_path / "real_wallet.dat") in results
    assert str(excluded_dir / "wallet.dat") not in results


def test_parallel_walk_excludes_a_wide_nested_subtree_with_many_workers(tmp_path):
    """Given excludes are configured, when a parallel walk runs, then
    excluded directories and their subtrees are never queued for any
    worker -- identical behavior to the sequential exclude logic today.
    Uses a wide tree (many top-level dirs so several workers genuinely
    race to claim work) with a deeply nested excluded subtree containing
    many matches, to catch a worker slipping past the exclude check."""
    excluded_dir = tmp_path / "excluded_root"
    for i in range(10):
        nested = excluded_dir / f"sub{i}" / "deeper"
        nested.mkdir(parents=True)
        (nested / f"wallet{i}.dat").write_bytes(b"x" * 100)

    allowed_matches = []
    for i in range(10):
        d = tmp_path / f"ok{i}"
        d.mkdir()
        wallet = d / "wallet.dat"
        wallet.write_bytes(b"x" * 100)
        allowed_matches.append(str(wallet))

    output_file = tmp_path / "out.txt"

    results = search_for_wallets(str(tmp_path), str(output_file), excludes=[str(excluded_dir)], walk_threads=8)

    assert sorted(results) == sorted(allowed_matches)
    assert set(output_file.read_text().splitlines()) == set(allowed_matches)


def test_parallel_walk_concurrent_matches_all_appear_exactly_once_in_output_file(tmp_path):
    """Given multiple worker threads find matching wallet files
    concurrently, when they write to output_file, then no writes are
    lost or interleaved-corrupted: a stress test with many simultaneous
    matches spread across many directories (so many workers are writing
    at once) asserts every match appears exactly once in both the
    returned result list and the on-disk output_file, and every line is
    a real, complete, unmangled path (not a torn/interleaved write)."""
    expected = []
    n_dirs = 120
    for i in range(n_dirs):
        d = tmp_path / f"stress{i}"
        d.mkdir()
        wallet = d / "wallet.dat"
        wallet.write_bytes(b"x" * 100)
        expected.append(str(wallet))

    output_file = tmp_path / "out.txt"

    results = search_for_wallets(str(tmp_path), str(output_file), walk_threads=8)

    assert sorted(results) == sorted(expected)
    assert len(results) == len(set(results))  # no duplicates from a lost/duplicated coordination bug

    lines = [line for line in output_file.read_text().splitlines() if line]
    assert sorted(lines) == sorted(expected)
    assert len(lines) == len(set(lines))  # no duplicate or corrupted-into-a-duplicate lines
    assert all(line in expected for line in lines)  # no torn/interleaved/mangled line snuck in


def test_walk_threads_of_one_behaves_like_a_single_worker(tmp_path):
    expected = _build_tree(tmp_path)
    output_file = tmp_path / "out.txt"

    results = search_for_wallets(str(tmp_path), str(output_file), walk_threads=1)

    assert sorted(results) == expected
