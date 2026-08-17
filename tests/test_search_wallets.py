import json

from tools.search_wallets import search_for_wallets


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
    small, fast test, so this writes a checkpoint directly -- simulating
    an interrupted prior run that had already fully walked `subdir`.
    """
    subdir = tmp_path / "already-scanned"
    subdir.mkdir()
    wallet_in_subdir = subdir / "wallet.dat"
    wallet_in_subdir.write_bytes(b"x" * 100)

    output_file = tmp_path / "out.txt"
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "start_path": str(tmp_path),
                "completed_dirs": [str(subdir)],
                "potential_wallets": [str(wallet_in_subdir)],
            }
        )
    )

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
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "start_path": "/some/other/path",
                "completed_dirs": [str(tmp_path)],
                "potential_wallets": ["/some/other/path/bogus.dat"],
            }
        )
    )

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
