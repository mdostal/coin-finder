import json
from unittest.mock import patch

from tools.analyze_wallets import _analyze_one_file, analyze_wallet_file, analyze_wallets
from tools.checkpoint_store import CheckpointStore
from tools.scan_index import is_known

# Tonight's real garbage: Rust mangled-symbol strings from a prior scan's
# own output file (wallet_analysis.json), re-scanned as if it were wallet
# content -- shape-matched Digibyte/Diamond Coin/Ripple with zero
# checksum verification. See config/address_validators.py and
# tests/test_address_validators.py for the offline validator these must
# now be filtered through.
GARBAGE_DIGIBYTE_AND_DIAMOND = "d6thread6Thread5cname17hd86fb86E"
GARBAGE_DIGIBYTE_ONLY = "df29a6dde7b3e33ab57f416f11"
REAL_BITCOIN_ADDRESS = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"


def _write_input_file(tmp_path, file_paths):
    input_file = tmp_path / "search_output.txt"
    input_file.write_text("\n".join(str(p) for p in file_paths))
    return input_file


def test_analyze_wallets_with_no_index_is_unchanged(tmp_path):
    """index_db_path=None (the default) must be a complete no-op --
    byte-identical to pre-dedup behavior."""
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_text("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")
    input_file = _write_input_file(tmp_path, [wallet_file])
    output_file = tmp_path / "analysis.json"

    analyze_wallets(str(input_file), str(output_file))

    result = json.loads(output_file.read_text())
    assert str(wallet_file) in result
    assert "Bitcoin" in result[str(wallet_file)]


@patch("tools.analyze_wallets.analyze_wallet_file")
def test_analyze_wallets_skips_regex_for_a_known_hash(mock_analyze_file, tmp_path):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_bytes(b"same content everywhere")
    input_file = _write_input_file(tmp_path, [wallet_file])
    output_file = tmp_path / "analysis.json"
    index_db_path = tmp_path / "scan_index.db"

    from tools.scan_index import hash_file_bytes, record_scanned_file

    file_hash = hash_file_bytes(b"same content everywhere")
    record_scanned_file(file_hash, "/some/other/path/wallet.dat", {"Bitcoin": ["1cached"]}, db_path=index_db_path)

    analyze_wallets(str(input_file), str(output_file), index_db_path=index_db_path)

    mock_analyze_file.assert_not_called()
    result = json.loads(output_file.read_text())
    assert result[str(wallet_file)] == {"Bitcoin": ["1cached"]}


def test_analyze_wallets_records_new_files_when_indexing(tmp_path):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_text("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")
    input_file = _write_input_file(tmp_path, [wallet_file])
    output_file = tmp_path / "analysis.json"
    index_db_path = tmp_path / "scan_index.db"

    analyze_wallets(str(input_file), str(output_file), index_db_path=index_db_path)

    file_hash_result = is_known(_sha256_of(wallet_file), db_path=index_db_path)
    assert file_hash_result is not None
    assert "Bitcoin" in file_hash_result


def test_analyze_wallets_recognizes_same_content_at_a_different_path(tmp_path):
    """The actual point of the feature: a copy on a different drive/backup
    (different path, identical bytes) is recognized as a duplicate."""
    content = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
    drive_a = tmp_path / "driveA"
    drive_a.mkdir()
    wallet_a = drive_a / "wallet.dat"
    wallet_a.write_text(content)
    index_db_path = tmp_path / "scan_index.db"

    analyze_wallets(str(_write_input_file(tmp_path, [wallet_a])), str(tmp_path / "out_a.json"), index_db_path=index_db_path)

    drive_b = tmp_path / "driveB_backup"
    drive_b.mkdir()
    wallet_b = drive_b / "wallet_copy.dat"
    wallet_b.write_text(content)

    with patch("tools.analyze_wallets.analyze_wallet_file") as mock_analyze_file:
        analyze_wallets(str(_write_input_file(tmp_path, [wallet_b])), str(tmp_path / "out_b.json"), index_db_path=index_db_path)
        mock_analyze_file.assert_not_called()


def _sha256_of(path):
    from tools.scan_index import hash_file_bytes

    return hash_file_bytes(path.read_bytes())


def test_analyze_wallets_reports_determinate_progress(tmp_path):
    wallet_a = tmp_path / "a.dat"
    wallet_a.write_text("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")
    wallet_b = tmp_path / "b.dat"
    wallet_b.write_text("nothing interesting here")
    input_file = _write_input_file(tmp_path, [wallet_a, wallet_b])
    output_file = tmp_path / "analysis.json"

    calls = []
    analyze_wallets(str(input_file), str(output_file), progress_callback=lambda c, t, m="": calls.append((c, t, m)))

    assert calls == [(1, 2, str(wallet_a)), (2, 2, str(wallet_b))]


def test_analyze_wallet_file_filters_out_garbage_matches(tmp_path):
    """End-to-end regression test for tonight's bug report: a file
    containing both a real, checksum-valid Bitcoin address and the actual
    garbage strings a prior scan's own output produced. Only the real
    address may survive -- garbage must never reach the returned dict,
    which is what tools/analyze_wallets.py:analyze_wallets() writes
    straight to wallet_analysis.json (and from there feeds real
    balance-check API calls and web/app.py's record_finding())."""
    wallet_file = tmp_path / "prior_scan_output.json"
    wallet_file.write_text(
        f"{REAL_BITCOIN_ADDRESS} {GARBAGE_DIGIBYTE_AND_DIAMOND} {GARBAGE_DIGIBYTE_ONLY}"
    )

    result = analyze_wallet_file(str(wallet_file))

    assert result.get("Bitcoin") == [REAL_BITCOIN_ADDRESS]
    for matches in result.values():
        assert GARBAGE_DIGIBYTE_AND_DIAMOND not in matches
        assert GARBAGE_DIGIBYTE_ONLY not in matches


def test_analyze_wallets_reports_progress_for_a_dedup_cache_hit_too(tmp_path):
    content = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
    wallet_a = tmp_path / "a.dat"
    wallet_a.write_text(content)
    index_db_path = tmp_path / "scan_index.db"
    analyze_wallets(str(_write_input_file(tmp_path, [wallet_a])), str(tmp_path / "out_a.json"), index_db_path=index_db_path)

    wallet_b = tmp_path / "b.dat"
    wallet_b.write_text(content)  # identical content -- a cache hit this time

    calls = []
    analyze_wallets(
        str(_write_input_file(tmp_path, [wallet_b])),
        str(tmp_path / "out_b.json"),
        index_db_path=index_db_path,
        progress_callback=lambda c, t, m="": calls.append((c, t, m)),
    )

    assert calls == [(1, 1, str(wallet_b))]


# ---------------------------------------------------------------------------
# sse-01: checkpoint_path (resume) + processes (multiprocessing.Pool)
# ---------------------------------------------------------------------------


class _FakePool:
    """
    Stands in for multiprocessing.Pool in tests -- per this repo's TDD
    conventions, real worker *processes* aren't needed to prove
    analyze_wallets()'s own dispatch/resume/checkpoint/scan_index
    orchestration logic is correct; only tests explicitly proving real
    multiprocessing works (see test_analyze_wallets_with_real_multiprocessing_pool_matches_sequential_result
    below) spin up a genuine Pool. Runs the worker function synchronously,
    in-process, so tests stay deterministic and fast.
    """

    instances = []

    def __init__(self, processes):
        self.processes = processes
        self.entered = False
        self.exited = False
        self.exited_with_exc = None
        _FakePool.instances.append(self)

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exited = True
        self.exited_with_exc = exc_type
        return False  # never swallow the exception

    def imap_unordered(self, fn, iterable):
        for item in iterable:
            yield fn(item)


class _RaisingFakePool(_FakePool):
    def imap_unordered(self, fn, iterable):
        for item in iterable:
            yield fn(item)  # first item raises via a poisoned analyze_wallet_file


def _write_checkpoint_store(checkpoint_path, input_file, completed_files):
    store = CheckpointStore(checkpoint_path, run_key={"input_file": str(input_file)})
    for file_path in completed_files:
        store.mark_completed(str(file_path))
    store.flush()
    store.close()


def test_analyze_wallets_resumes_by_skipping_already_completed_files(tmp_path):
    already_done = tmp_path / "already_done.dat"
    already_done.write_text("nothing checked again")
    new_file = tmp_path / "new_file.dat"
    new_file.write_text("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")
    input_file = _write_input_file(tmp_path, [already_done, new_file])
    output_file = tmp_path / "analysis.json"
    checkpoint_path = tmp_path / "analyze_checkpoint.db"
    _write_checkpoint_store(checkpoint_path, input_file, [already_done])

    with patch("tools.analyze_wallets.analyze_wallet_file") as mock_analyze_file:
        mock_analyze_file.return_value = {"Bitcoin": ["1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"]}
        analyze_wallets(str(input_file), str(output_file), checkpoint_path=str(checkpoint_path))

    mock_analyze_file.assert_called_once_with(str(new_file))
    result = json.loads(output_file.read_text())
    assert str(already_done) not in result
    assert result[str(new_file)] == {"Bitcoin": ["1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"]}


def test_analyze_wallets_deletes_checkpoint_on_clean_completion(tmp_path):
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_text("nothing interesting")
    input_file = _write_input_file(tmp_path, [wallet_file])
    output_file = tmp_path / "analysis.json"
    checkpoint_path = tmp_path / "analyze_checkpoint.db"

    analyze_wallets(str(input_file), str(output_file), checkpoint_path=str(checkpoint_path))

    assert not checkpoint_path.exists()


def test_analyze_wallets_with_no_checkpoint_path_is_unchanged(tmp_path):
    """checkpoint_path=None (the default) must be a complete no-op --
    byte-identical to pre-resume behavior."""
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_text("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")
    input_file = _write_input_file(tmp_path, [wallet_file])
    output_file = tmp_path / "analysis.json"

    analyze_wallets(str(input_file), str(output_file))

    result = json.loads(output_file.read_text())
    assert str(wallet_file) in result


def test_analyze_wallet_one_file_worker_never_touches_scan_index(tmp_path):
    """The critical constraint: worker processes must never read or write
    scan_index.db -- only the main process does, so multiprocessing never
    introduces concurrent writers to it. _analyze_one_file is the exact
    function dispatched to multiprocessing.Pool workers; calling it
    directly (as a worker process would) must not touch scan_index.py at
    all."""
    wallet_file = tmp_path / "wallet.dat"
    wallet_file.write_text("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")

    with patch("tools.analyze_wallets.record_scanned_file") as mock_record, \
         patch("tools.analyze_wallets.is_known") as mock_is_known:
        file_path, results = _analyze_one_file(str(wallet_file))

    mock_record.assert_not_called()
    mock_is_known.assert_not_called()
    assert file_path == str(wallet_file)
    assert results.get("Bitcoin") == ["1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"]


@patch("tools.analyze_wallets.Pool", _FakePool)
def test_analyze_wallets_with_processes_greater_than_one_uses_a_pool(tmp_path):
    wallet_a = tmp_path / "a.dat"
    wallet_a.write_text("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")
    wallet_b = tmp_path / "b.dat"
    wallet_b.write_text("nothing interesting here")
    input_file = _write_input_file(tmp_path, [wallet_a, wallet_b])
    output_file = tmp_path / "analysis.json"
    _FakePool.instances.clear()

    analyze_wallets(str(input_file), str(output_file), processes=4)

    assert len(_FakePool.instances) == 1
    pool = _FakePool.instances[0]
    assert pool.processes == 4
    assert pool.entered and pool.exited
    result = json.loads(output_file.read_text())
    assert "Bitcoin" in result[str(wallet_a)]
    assert str(wallet_b) not in result


@patch("tools.analyze_wallets.Pool", _FakePool)
def test_analyze_wallets_with_processes_matches_sequential_result(tmp_path):
    wallet_a = tmp_path / "a.dat"
    wallet_a.write_text("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")
    wallet_b = tmp_path / "b.dat"
    wallet_b.write_text("nothing interesting here")
    wallet_c = tmp_path / "c.dat"
    wallet_c.write_text("0x71C7656EC7ab88b098defB751B7401B5f6d8976")

    sequential_output = tmp_path / "sequential.json"
    analyze_wallets(
        str(_write_input_file(tmp_path, [wallet_a, wallet_b, wallet_c])),
        str(sequential_output),
    )

    parallel_output = tmp_path / "parallel.json"
    analyze_wallets(
        str(_write_input_file(tmp_path, [wallet_a, wallet_b, wallet_c])),
        str(parallel_output),
        processes=3,
    )

    assert json.loads(sequential_output.read_text()) == json.loads(parallel_output.read_text())


@patch("tools.analyze_wallets.Pool", _FakePool)
def test_analyze_wallets_processes_dispatches_only_files_needing_fresh_analysis(tmp_path):
    """A resumed or dedup-cached file is never dispatched to the pool at
    all -- filtered out up front in the main process, exactly like the
    sequential path."""
    already_done = tmp_path / "already_done.dat"
    already_done.write_text("skip me")
    new_file = tmp_path / "new_file.dat"
    new_file.write_text("nothing to find")
    input_file = _write_input_file(tmp_path, [already_done, new_file])
    output_file = tmp_path / "analysis.json"
    checkpoint_path = tmp_path / "analyze_checkpoint.db"
    _write_checkpoint_store(checkpoint_path, input_file, [already_done])
    _FakePool.instances.clear()

    with patch("tools.analyze_wallets.analyze_wallet_file") as mock_analyze_file:
        mock_analyze_file.return_value = {}
        analyze_wallets(str(input_file), str(output_file), checkpoint_path=str(checkpoint_path), processes=2)

    mock_analyze_file.assert_called_once_with(str(new_file))


@patch("tools.analyze_wallets.Pool", _FakePool)
def test_analyze_wallets_processes_reports_progress_for_every_file_exactly_once(tmp_path):
    wallet_a = tmp_path / "a.dat"
    wallet_a.write_text("a")
    wallet_b = tmp_path / "b.dat"
    wallet_b.write_text("b")
    input_file = _write_input_file(tmp_path, [wallet_a, wallet_b])
    output_file = tmp_path / "analysis.json"

    calls = []
    analyze_wallets(
        str(input_file),
        str(output_file),
        processes=2,
        progress_callback=lambda c, t, m="": calls.append((c, t, m)),
    )

    assert len(calls) == 2
    assert [c[0] for c in calls] == [1, 2]  # a strictly increasing count
    assert all(t == 2 for _, t, _ in calls)
    assert {m for _, _, m in calls} == {str(wallet_a), str(wallet_b)}


@patch("tools.analyze_wallets.Pool", _FakePool)
def test_analyze_wallets_processes_writes_scan_index_only_from_the_main_process(tmp_path):
    """Zero-concurrent-writers guarantee: record_scanned_file is called
    exactly once per newly-analyzed file, and only from analyze_wallets()'s
    own main-process result loop -- never from inside the (fake, but
    interface-faithful) pool's worker call."""
    wallet_a = tmp_path / "a.dat"
    wallet_a.write_text("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")
    wallet_b = tmp_path / "b.dat"
    wallet_b.write_text("nothing interesting here")
    input_file = _write_input_file(tmp_path, [wallet_a, wallet_b])
    output_file = tmp_path / "analysis.json"
    index_db_path = tmp_path / "scan_index.db"

    with patch("tools.analyze_wallets.record_scanned_file") as mock_record:
        analyze_wallets(str(input_file), str(output_file), index_db_path=index_db_path, processes=2)

    assert mock_record.call_count == 2
    called_paths = {call.args[1] for call in mock_record.call_args_list}
    assert called_paths == {str(wallet_a), str(wallet_b)}


def test_analyze_wallets_worker_exception_propagates_and_pool_is_still_cleaned_up(tmp_path):
    wallet_a = tmp_path / "a.dat"
    wallet_a.write_text("boom")
    input_file = _write_input_file(tmp_path, [wallet_a])
    output_file = tmp_path / "analysis.json"
    _FakePool.instances.clear()

    with patch("tools.analyze_wallets.Pool", _RaisingFakePool), \
         patch("tools.analyze_wallets.analyze_wallet_file", side_effect=RuntimeError("worker blew up")):
        try:
            analyze_wallets(str(input_file), str(output_file), processes=2)
            raised = False
        except RuntimeError:
            raised = True

    assert raised
    assert len(_FakePool.instances) == 1
    pool = _FakePool.instances[0]
    # mirrors check_wallet_balances.py's future.result() re-raise pattern:
    # the exception surfaces to the caller, but the pool's own context
    # manager still ran its cleanup (__exit__) rather than being left
    # hanging/corrupted.
    assert pool.exited
    assert pool.exited_with_exc is RuntimeError


def test_analyze_wallets_with_real_multiprocessing_pool_matches_sequential_result(tmp_path):
    """One real (non-mocked) end-to-end proof that multiprocessing.Pool
    parallelism actually works -- pickling a plain file path string to a
    module-level worker function, real separate processes -- not just
    that the fake-pool-driven orchestration tests above are internally
    consistent."""
    wallet_a = tmp_path / "a.dat"
    wallet_a.write_text("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")
    wallet_b = tmp_path / "b.dat"
    wallet_b.write_text("0x71C7656EC7ab88b098defB751B7401B5f6d8976")

    sequential_output = tmp_path / "sequential.json"
    analyze_wallets(str(_write_input_file(tmp_path, [wallet_a, wallet_b])), str(sequential_output))

    real_pool_output = tmp_path / "real_pool.json"
    analyze_wallets(
        str(_write_input_file(tmp_path, [wallet_a, wallet_b])),
        str(real_pool_output),
        processes=2,
    )

    assert json.loads(sequential_output.read_text()) == json.loads(real_pool_output.read_text())
