import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.check_wallet_balances import (
    GLOBAL_MAX_WORKERS,
    PER_COIN_MAX_CONCURRENCY,
    _check_balance_with_retries,
    _checkpoint_unit_id,
    _decode_checkpoint_unit_id,
    check_wallet_balances,
)
from tools.checkpoint_store import CheckpointStore


def make_service(side_effect):
    service = MagicMock()
    service.check_balance = MagicMock(side_effect=side_effect)
    return service


@patch("tools.check_wallet_balances.time.sleep")
def test_immediate_success_does_not_retry(mock_sleep):
    service = make_service([5.0])

    result = _check_balance_with_retries(service, "addr", max_retries=3, backoff_seconds=2)

    assert result == 5.0
    assert service.check_balance.call_count == 1
    mock_sleep.assert_not_called()


@patch("tools.check_wallet_balances.time.sleep")
def test_eventual_success_stops_retrying_once_confirmed(mock_sleep):
    service = make_service([None, None, 3.0])

    result = _check_balance_with_retries(service, "addr", max_retries=3, backoff_seconds=2)

    assert result == 3.0
    assert service.check_balance.call_count == 3
    assert mock_sleep.call_count == 2


@patch("tools.check_wallet_balances.time.sleep")
def test_exhausted_retries_returns_none_without_sleeping_after_final_attempt(mock_sleep):
    service = make_service([None, None, None])

    result = _check_balance_with_retries(service, "addr", max_retries=3, backoff_seconds=2)

    assert result is None
    assert service.check_balance.call_count == 3
    assert mock_sleep.call_count == 2  # sleeps between attempts, never after the last


@patch("tools.check_wallet_balances.time.sleep")
def test_confirmed_zero_balance_is_not_retried(mock_sleep):
    service = make_service([0.0])

    result = _check_balance_with_retries(service, "addr", max_retries=3, backoff_seconds=2)

    assert result == 0.0
    assert service.check_balance.call_count == 1
    mock_sleep.assert_not_called()


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_inconclusive_address_after_retries_is_written_to_inconclusive_file(
    mock_load_service, mock_sleep, tmp_path
):
    mock_load_service.return_value = make_service([None, None, None])

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": ["1abc"]}}))
    output_file = tmp_path / "wallet_balances.json"

    check_wallet_balances(str(input_file), str(output_file), coins_to_check=["Bitcoin"])

    inconclusive_file = tmp_path / "inconclusive_balances.json"
    assert inconclusive_file.exists()
    assert json.loads(inconclusive_file.read_text()) == {"walletA.dat": {"Bitcoin": ["1abc"]}}


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_no_inconclusive_file_written_when_nothing_is_inconclusive(
    mock_load_service, mock_sleep, tmp_path
):
    mock_load_service.return_value = make_service([0.0])

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": ["1abc"]}}))
    output_file = tmp_path / "wallet_balances.json"

    check_wallet_balances(str(input_file), str(output_file), coins_to_check=["Bitcoin"])

    inconclusive_file = tmp_path / "inconclusive_balances.json"
    assert not inconclusive_file.exists()

    balances = json.loads(output_file.read_text())
    assert balances["walletA.dat"]["Bitcoin"]["1abc"] == 0.0


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_inconclusive_output_path_is_overridable(mock_load_service, mock_sleep, tmp_path):
    mock_load_service.return_value = make_service([None, None, None])

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": ["1abc"]}}))
    output_file = tmp_path / "wallet_balances.json"
    custom_inconclusive = tmp_path / "custom_inconclusive.json"

    check_wallet_balances(
        str(input_file),
        str(output_file),
        coins_to_check=["Bitcoin"],
        inconclusive_output=str(custom_inconclusive),
    )

    assert custom_inconclusive.exists()
    assert not (tmp_path / "inconclusive_balances.json").exists()


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_progress_callback_invoked_once_per_address(mock_load_service, mock_sleep, tmp_path):
    mock_load_service.return_value = make_service([0.0, 1.5])

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": ["1abc", "1def"]}}))
    output_file = tmp_path / "wallet_balances.json"

    calls = []
    check_wallet_balances(
        str(input_file),
        str(output_file),
        coins_to_check=["Bitcoin"],
        progress_callback=lambda current, total, message="": calls.append((current, total)),
    )

    assert calls == [(1, 2), (2, 2)]


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_no_progress_callback_is_unaffected(mock_load_service, mock_sleep, tmp_path):
    mock_load_service.return_value = make_service([0.0])

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": ["1abc"]}}))
    output_file = tmp_path / "wallet_balances.json"

    result = check_wallet_balances(str(input_file), str(output_file), coins_to_check=["Bitcoin"])

    assert result["walletA.dat"]["Bitcoin"]["1abc"] == 0.0


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_different_coins_are_checked_concurrently(mock_load_service, mock_sleep, tmp_path):
    """
    The real complaint this story fixes: every coin's own independent
    service/API used to be checked one at a time, in one thread. Two
    services here each block until the OTHER has started -- if coins are
    still checked serially, the second coin's worker never starts while
    the first is blocked waiting for it, so this deadlocks and times out.
    """
    bitcoin_started = threading.Event()
    litecoin_started = threading.Event()

    def make_blocking_service(own_started, other_started):
        def check_balance(address):
            own_started.set()
            assert other_started.wait(timeout=2), "the other coin's call never started -- coins are being checked serially, not concurrently"
            return 1.0

        service = MagicMock()
        service.check_balance = MagicMock(side_effect=check_balance)
        return service

    services = {
        "Bitcoin": make_blocking_service(bitcoin_started, litecoin_started),
        "Litecoin": make_blocking_service(litecoin_started, bitcoin_started),
    }
    mock_load_service.side_effect = lambda coin: services[coin]

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": ["1abc"], "Litecoin": ["Labc"]}}))
    output_file = tmp_path / "wallet_balances.json"

    result = check_wallet_balances(str(input_file), str(output_file), coins_to_check=["Bitcoin", "Litecoin"])

    assert result == {"walletA.dat": {"Bitcoin": {"1abc": 1.0}, "Litecoin": {"Labc": 1.0}}}


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_progress_callback_thread_safe_across_multiple_coins(mock_load_service, mock_sleep, tmp_path):
    mock_load_service.side_effect = lambda coin: MagicMock(check_balance=MagicMock(return_value=1.0))

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": ["1abc", "1def"], "Litecoin": ["Labc", "Ldef"]}}))
    output_file = tmp_path / "wallet_balances.json"

    calls = []
    calls_lock = threading.Lock()

    def cb(current, total, message=""):
        with calls_lock:
            calls.append((current, total))

    check_wallet_balances(str(input_file), str(output_file), coins_to_check=["Bitcoin", "Litecoin"], progress_callback=cb)

    assert len(calls) == 4
    assert all(total == 4 for _, total in calls)
    assert sorted(current for current, _ in calls) == [1, 2, 3, 4]


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_multi_coin_multi_file_output_matches_expected_nested_dict(mock_load_service, mock_sleep, tmp_path):
    values = {"Bitcoin": 1.0, "Litecoin": 2.0}
    mock_load_service.side_effect = lambda coin: MagicMock(check_balance=MagicMock(return_value=values[coin]))

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(
        json.dumps(
            {
                "walletA.dat": {"Bitcoin": ["1abc"], "Litecoin": ["Labc"]},
                "walletB.dat": {"Bitcoin": ["1def"]},
            }
        )
    )
    output_file = tmp_path / "wallet_balances.json"

    result = check_wallet_balances(str(input_file), str(output_file), coins_to_check=["Bitcoin", "Litecoin"])

    assert result == {
        "walletA.dat": {"Bitcoin": {"1abc": 1.0}, "Litecoin": {"Labc": 2.0}},
        "walletB.dat": {"Bitcoin": {"1def": 1.0}},
    }


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_addresses_within_one_coin_are_checked_concurrently(mock_load_service, mock_sleep, tmp_path):
    """
    The real bug this fixes: "parallel by coin" bought nothing once a scan
    was mostly one coin (the realistic case) -- every one of that coin's
    addresses still ran strictly one at a time, in a single thread. Two
    addresses of the SAME coin here each block until the OTHER has
    started; if they're still checked serially, the second address's call
    never starts while the first is blocked waiting for it, so this
    deadlocks and times out.
    """
    first_started = threading.Event()
    second_started = threading.Event()
    started_by_address = {"1abc": first_started, "1def": second_started}
    other_by_address = {"1abc": second_started, "1def": first_started}

    def check_balance(address):
        started_by_address[address].set()
        assert other_by_address[address].wait(timeout=2), (
            "the other address's call never started -- addresses within a coin are still being checked serially"
        )
        return 1.0

    service = MagicMock()
    service.check_balance = MagicMock(side_effect=check_balance)
    mock_load_service.return_value = service

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": ["1abc", "1def"]}}))
    output_file = tmp_path / "wallet_balances.json"

    result = check_wallet_balances(str(input_file), str(output_file), coins_to_check=["Bitcoin"])

    assert result == {"walletA.dat": {"Bitcoin": {"1abc": 1.0, "1def": 1.0}}}


@patch("tools.check_wallet_balances.load_service")
def test_per_coin_concurrency_is_capped(mock_load_service, tmp_path):
    """
    No @patch on time.sleep here deliberately: `time` is a shared module
    singleton, so patching tools.check_wallet_balances.time.sleep patches
    the real, global time.sleep process-wide -- which would silently turn
    this test's own synchronization wait into a no-op too. Not needed
    anyway: check_balance below always succeeds on the first try, so the
    retry backoff path (the only thing that ever calls time.sleep) never
    triggers.
    """
    concurrent = 0
    max_concurrent = 0
    lock = threading.Lock()
    release = threading.Event()
    ramped_up = threading.Event()

    def check_balance(address):
        nonlocal concurrent, max_concurrent
        with lock:
            concurrent += 1
            max_concurrent = max(max_concurrent, concurrent)
            if concurrent >= PER_COIN_MAX_CONCURRENCY:
                ramped_up.set()
        release.wait(timeout=2)
        with lock:
            concurrent -= 1
        return 1.0

    service = MagicMock()
    service.check_balance = MagicMock(side_effect=check_balance)
    mock_load_service.return_value = service

    addresses = [f"addr{i}" for i in range(PER_COIN_MAX_CONCURRENCY + 5)]
    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": addresses}}))
    output_file = tmp_path / "wallet_balances.json"

    def run():
        check_wallet_balances(str(input_file), str(output_file), coins_to_check=["Bitcoin"])

    t = threading.Thread(target=run)
    t.start()
    assert ramped_up.wait(timeout=2), "never reached the expected per-coin concurrency cap"
    release.set()
    t.join(timeout=3)

    assert max_concurrent <= PER_COIN_MAX_CONCURRENCY


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_checkpoint_deleted_on_clean_completion(mock_load_service, mock_sleep, tmp_path):
    mock_load_service.return_value = make_service([1.0])

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": ["1abc"]}}))
    output_file = tmp_path / "wallet_balances.json"
    checkpoint_path = tmp_path / "checkpoint.db"

    check_wallet_balances(
        str(input_file), str(output_file), coins_to_check=["Bitcoin"], checkpoint_path=str(checkpoint_path)
    )

    assert not checkpoint_path.exists()
    assert not Path(f"{checkpoint_path}-wal").exists()
    assert not Path(f"{checkpoint_path}-shm").exists()


def test_checkpoint_unit_id_round_trips_crypto_file_address_and_balance():
    unit_id = _checkpoint_unit_id("Bitcoin", "walletA.dat", "1abc", 2.5)

    assert _decode_checkpoint_unit_id(unit_id) == ("Bitcoin", "walletA.dat", "1abc", 2.5)


def test_checkpoint_unit_id_round_trips_a_zero_balance():
    """0.0 is a real, confirmed balance -- must never be confused with the
    None/'not yet confirmed' case on the decode side."""
    unit_id = _checkpoint_unit_id("Bitcoin", "walletA.dat", "1abc", 0.0)

    assert _decode_checkpoint_unit_id(unit_id) == ("Bitcoin", "walletA.dat", "1abc", 0.0)


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_checkpoint_is_a_sqlite_checkpoint_store_not_a_full_json_rewrite(mock_load_service, mock_sleep, tmp_path):
    """
    Regression test for the real bug this story fixes: the old
    _flush_checkpoint() did a full json.dump() of the entire in-memory
    results dict on every periodic flush. The checkpoint file on disk must
    now be a CheckpointStore-backed sqlite db -- never JSON -- holding one
    row per confirmed (coin, file_path, address) unit.
    """
    mock_load_service.return_value = make_service([1.0])

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": ["1abc"]}}))
    output_file = tmp_path / "wallet_balances.json"
    checkpoint_path = tmp_path / "checkpoint.db"

    # Clean completion deletes the checkpoint (see
    # test_checkpoint_deleted_on_clean_completion) -- disable that here so
    # the on-disk format can be inspected afterwards.
    with patch("tools.check_wallet_balances.CheckpointStore.delete", lambda self: self.close()):
        check_wallet_balances(
            str(input_file), str(output_file), coins_to_check=["Bitcoin"], checkpoint_path=str(checkpoint_path)
        )

    # Old format was UTF-8 JSON text; the new format is a raw sqlite file
    # (binary, starts with the "SQLite format 3" magic header) -- neither
    # decodes as JSON.
    with pytest.raises((UnicodeDecodeError, json.JSONDecodeError)):
        json.loads(checkpoint_path.read_text())

    conn = sqlite3.connect(str(checkpoint_path))
    rows = conn.execute("SELECT unit_id FROM completed_units").fetchall()
    conn.close()

    assert len(rows) == 1
    assert _decode_checkpoint_unit_id(rows[0][0]) == ("Bitcoin", "walletA.dat", "1abc", 1.0)


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_resume_skips_confirmed_addresses_and_retries_inconclusive_ones(mock_load_service, mock_sleep, tmp_path):
    """
    Regression test for the real ask: a balance check killed mid-run
    (app quit/update/crash) shouldn't have to re-check addresses it
    already confirmed a real balance for. Addresses still inconclusive
    after retries ARE retried on resume, since a fresh run may succeed
    where a stale one didn't -- exactly the same behavior as before this
    story, just backed by CheckpointStore instead of a full-dict JSON file.
    """
    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(
        json.dumps({"walletA.dat": {"Bitcoin": ["confirmed-addr", "inconclusive-addr", "new-addr"]}})
    )
    output_file = tmp_path / "wallet_balances.json"
    checkpoint_path = tmp_path / "checkpoint.db"

    store = CheckpointStore(str(checkpoint_path), run_key={"input_file": str(input_file)})
    store.mark_completed(_checkpoint_unit_id("Bitcoin", "walletA.dat", "confirmed-addr", 2.5))
    store.flush()
    store.close()
    # "inconclusive-addr" is deliberately NOT marked completed -- only
    # confirmed (non-None) balances are ever recorded (see check_one()),
    # so an address that was still inconclusive when the checkpoint was
    # last written simply has no row at all, and is retried like any
    # never-checked address.

    calls = []

    def check_balance(address):
        calls.append(address)
        return 9.0

    service = MagicMock()
    service.check_balance = MagicMock(side_effect=check_balance)
    mock_load_service.return_value = service

    result = check_wallet_balances(
        str(input_file), str(output_file), coins_to_check=["Bitcoin"], checkpoint_path=str(checkpoint_path)
    )

    assert "confirmed-addr" not in calls
    assert sorted(calls) == ["inconclusive-addr", "new-addr"]
    assert result["walletA.dat"]["Bitcoin"]["confirmed-addr"] == 2.5
    assert result["walletA.dat"]["Bitcoin"]["inconclusive-addr"] == 9.0
    assert result["walletA.dat"]["Bitcoin"]["new-addr"] == 9.0
    assert not checkpoint_path.exists()


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_pauses_cleanly_without_starting_new_requests(mock_load_service, mock_sleep, tmp_path, monkeypatch):
    """
    sse-04 confirmed pause semantics: let in-flight work finish, never
    abort mid-write ("no NEW request starts" -- structured-outline.md Q4).
    per_coin_max_concurrency=1/global_max_workers=1 makes this
    deterministic: addresses are strictly serialized, so exactly one
    address is genuinely in flight at a time. CHECKPOINT_EVERY_ADDRESSES
    is forced to 1 so the very first confirmed address's flush is the one
    that notices the pre-set pause flag.
    """
    import tools.check_wallet_balances as check_wallet_balances_module
    from tools.checkpoint_store import CheckpointPaused, request_pause_for

    monkeypatch.setattr(check_wallet_balances_module, "CHECKPOINT_EVERY_ADDRESSES", 1)

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": ["addr1", "addr2", "addr3"]}}))
    output_file = tmp_path / "wallet_balances.json"
    checkpoint_path = tmp_path / "checkpoint.db"

    store = CheckpointStore(str(checkpoint_path), run_key={"input_file": str(input_file)})
    store.close()
    request_pause_for(str(checkpoint_path))

    calls = []

    def check_balance(address):
        calls.append(address)
        return 1.0

    mock_load_service.return_value = make_service(check_balance)

    with pytest.raises(CheckpointPaused):
        check_wallet_balances(
            str(input_file),
            str(output_file),
            coins_to_check=["Bitcoin"],
            checkpoint_path=str(checkpoint_path),
            per_coin_max_concurrency=1,
            global_max_workers=1,
        )

    assert calls == ["addr1"]  # only the already-in-flight address ran
    assert checkpoint_path.exists()  # never deleted on a pause
    assert not output_file.exists()  # no partial output written

    conn = sqlite3.connect(str(checkpoint_path))
    completed = conn.execute("SELECT COUNT(*) FROM completed_units").fetchone()[0]
    conn.close()
    assert completed == 1  # durably recorded before the pause was raised


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_resumes_after_being_paused(mock_load_service, mock_sleep, tmp_path, monkeypatch):
    import tools.check_wallet_balances as check_wallet_balances_module
    from tools.checkpoint_store import CheckpointPaused, clear_pause_for, request_pause_for

    monkeypatch.setattr(check_wallet_balances_module, "CHECKPOINT_EVERY_ADDRESSES", 1)

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": ["addr1", "addr2", "addr3"]}}))
    output_file = tmp_path / "wallet_balances.json"
    checkpoint_path = tmp_path / "checkpoint.db"

    store = CheckpointStore(str(checkpoint_path), run_key={"input_file": str(input_file)})
    store.close()
    request_pause_for(str(checkpoint_path))

    calls = []

    def check_balance(address):
        calls.append(address)
        return 1.0

    mock_load_service.return_value = make_service(check_balance)

    with pytest.raises(CheckpointPaused):
        check_wallet_balances(
            str(input_file),
            str(output_file),
            coins_to_check=["Bitcoin"],
            checkpoint_path=str(checkpoint_path),
            per_coin_max_concurrency=1,
            global_max_workers=1,
        )

    clear_pause_for(str(checkpoint_path))
    result = check_wallet_balances(
        str(input_file),
        str(output_file),
        coins_to_check=["Bitcoin"],
        checkpoint_path=str(checkpoint_path),
        per_coin_max_concurrency=1,
        global_max_workers=1,
    )

    assert sorted(calls) == ["addr1", "addr2", "addr3"]  # addr1 never re-checked
    assert result["walletA.dat"]["Bitcoin"] == {"addr1": 1.0, "addr2": 1.0, "addr3": 1.0}
    assert not checkpoint_path.exists()


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_checkpoint_ignored_for_a_different_input_file(mock_load_service, mock_sleep, tmp_path):
    """CheckpointStore's own run-key-mismatch handling (sse-01) wipes a
    checkpoint recorded under a different input_file -- this just proves
    check_wallet_balances() actually keys its store on input_file, same
    as the old JSON checkpoint's own input_file guard."""
    mock_load_service.return_value = make_service([5.0])

    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": ["1abc"]}}))
    output_file = tmp_path / "wallet_balances.json"
    checkpoint_path = tmp_path / "checkpoint.db"

    store = CheckpointStore(str(checkpoint_path), run_key={"input_file": "/some/other/input.json"})
    store.mark_completed(_checkpoint_unit_id("Bitcoin", "walletA.dat", "1abc", 999.0))
    store.flush()
    store.close()

    result = check_wallet_balances(
        str(input_file), str(output_file), coins_to_check=["Bitcoin"], checkpoint_path=str(checkpoint_path)
    )

    assert result["walletA.dat"]["Bitcoin"]["1abc"] == 5.0


def test_worker_count_parameters_default_to_todays_tuned_constants():
    """GLOBAL_MAX_WORKERS/PER_COIN_MAX_CONCURRENCY becoming parameters
    must be zero behavior change for every existing caller that doesn't
    pass them explicitly."""
    import inspect

    sig = inspect.signature(check_wallet_balances)
    assert sig.parameters["global_max_workers"].default == GLOBAL_MAX_WORKERS == 64
    assert sig.parameters["per_coin_max_concurrency"].default == PER_COIN_MAX_CONCURRENCY == 15


@patch("tools.check_wallet_balances.load_service")
def test_custom_per_coin_max_concurrency_parameter_is_honored(mock_load_service, tmp_path):
    """Same shape as test_per_coin_concurrency_is_capped, but proving the
    *parameter* (not just the module constant) actually bounds concurrency."""
    custom_cap = 3
    concurrent = 0
    max_concurrent = 0
    lock = threading.Lock()
    release = threading.Event()
    ramped_up = threading.Event()

    def check_balance(address):
        nonlocal concurrent, max_concurrent
        with lock:
            concurrent += 1
            max_concurrent = max(max_concurrent, concurrent)
            if concurrent >= custom_cap:
                ramped_up.set()
        release.wait(timeout=2)
        with lock:
            concurrent -= 1
        return 1.0

    service = MagicMock()
    service.check_balance = MagicMock(side_effect=check_balance)
    mock_load_service.return_value = service

    addresses = [f"addr{i}" for i in range(custom_cap + 5)]
    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": addresses}}))
    output_file = tmp_path / "wallet_balances.json"

    def run():
        check_wallet_balances(
            str(input_file), str(output_file), coins_to_check=["Bitcoin"], per_coin_max_concurrency=custom_cap
        )

    t = threading.Thread(target=run)
    t.start()
    assert ramped_up.wait(timeout=2), "never reached the expected custom per-coin concurrency cap"
    release.set()
    t.join(timeout=3)

    assert max_concurrent <= custom_cap


@patch("tools.check_wallet_balances.time.sleep")
@patch("tools.check_wallet_balances.load_service")
def test_custom_global_max_workers_parameter_is_passed_to_the_thread_pool(mock_load_service, mock_sleep, tmp_path):
    mock_load_service.return_value = make_service([1.0, 1.0, 1.0])

    addresses = [f"addr{i}" for i in range(3)]
    input_file = tmp_path / "wallet_analysis.json"
    input_file.write_text(json.dumps({"walletA.dat": {"Bitcoin": addresses}}))
    output_file = tmp_path / "wallet_balances.json"

    with patch("tools.check_wallet_balances.ThreadPoolExecutor", wraps=ThreadPoolExecutor) as mock_pool:
        check_wallet_balances(
            str(input_file), str(output_file), coins_to_check=["Bitcoin"], global_max_workers=2
        )

    assert mock_pool.call_args.kwargs["max_workers"] == 2  # min(3 tasks, 2 custom) == 2
