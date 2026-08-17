import sqlite3
import time

from web.auto_unlock_history import (
    clear_auto_unlock_history,
    latest_status_by_wallet_path,
    list_auto_unlock_history,
    record_auto_unlock_run,
)


def test_record_then_list_includes_every_wallet_from_the_run(tmp_path):
    db_path = tmp_path / "auto_unlock_history.db"

    record_auto_unlock_run(
        {
            "/wallets/a.dat": {"vault_label": "password-1", "value": "hunter2!!"},
            "/wallets/b.dat": {"vault_label": None, "value": None},
        },
        db_path=db_path,
    )

    runs = list_auto_unlock_history(db_path=db_path)
    assert len(runs) == 1
    wallets = {w["wallet_path"]: w for w in runs[0]["wallets"]}
    assert wallets["/wallets/a.dat"]["vault_label"] == "password-1"
    assert wallets["/wallets/a.dat"]["matched"] is True
    assert wallets["/wallets/b.dat"]["vault_label"] is None
    assert wallets["/wallets/b.dat"]["matched"] is False


def test_record_never_persists_the_raw_matched_value():
    """
    Schema-level guarantee, not just an application-level promise: no
    column for the raw password/value exists in the table at all.
    """
    import web.auto_unlock_history as auto_unlock_history_module

    assert "value" not in auto_unlock_history_module._SCHEMA.lower()
    assert "password" not in auto_unlock_history_module._SCHEMA.lower()


def test_record_never_persists_the_raw_matched_value_introspected_via_pragma(tmp_path):
    db_path = tmp_path / "auto_unlock_history.db"
    record_auto_unlock_run({"/wallets/a.dat": {"vault_label": "password-1", "value": "hunter2!!"}}, db_path=db_path)

    conn = sqlite3.connect(str(db_path))
    columns = {row[1] for row in conn.execute("PRAGMA table_info(auto_unlock_runs)").fetchall()}
    conn.close()

    assert columns == {"id", "run_id", "wallet_path", "vault_label", "matched", "run_at"}
    assert "value" not in columns


def test_list_auto_unlock_history_newest_run_first(tmp_path):
    db_path = tmp_path / "auto_unlock_history.db"
    record_auto_unlock_run({"/wallets/old.dat": {"vault_label": None, "value": None}}, db_path=db_path)
    time.sleep(0.01)
    record_auto_unlock_run({"/wallets/new.dat": {"vault_label": None, "value": None}}, db_path=db_path)

    runs = list_auto_unlock_history(db_path=db_path)
    assert runs[0]["wallets"][0]["wallet_path"] == "/wallets/new.dat"
    assert runs[1]["wallets"][0]["wallet_path"] == "/wallets/old.dat"


def test_each_call_gets_its_own_distinct_run_id(tmp_path):
    db_path = tmp_path / "auto_unlock_history.db"
    record_auto_unlock_run({"/wallets/a.dat": {"vault_label": None, "value": None}}, db_path=db_path)
    record_auto_unlock_run({"/wallets/b.dat": {"vault_label": None, "value": None}}, db_path=db_path)

    runs = list_auto_unlock_history(db_path=db_path)
    assert len(runs) == 2
    assert runs[0]["run_id"] != runs[1]["run_id"]


def test_clear_auto_unlock_history_deletes_everything(tmp_path):
    db_path = tmp_path / "auto_unlock_history.db"
    record_auto_unlock_run({"/wallets/a.dat": {"vault_label": None, "value": None}}, db_path=db_path)

    clear_auto_unlock_history(db_path=db_path)

    assert list_auto_unlock_history(db_path=db_path) == []


def test_connect_creates_parent_directory(tmp_path):
    db_path = tmp_path / "nested" / "dir" / "auto_unlock_history.db"
    record_auto_unlock_run({"/wallets/a.dat": {"vault_label": None, "value": None}}, db_path=db_path)
    assert db_path.exists()


def test_latest_status_by_wallet_path_empty_when_no_history(tmp_path):
    db_path = tmp_path / "auto_unlock_history.db"
    assert latest_status_by_wallet_path(db_path=db_path) == {}


def test_latest_status_by_wallet_path_reflects_matched_row(tmp_path):
    db_path = tmp_path / "auto_unlock_history.db"
    record_auto_unlock_run({"/wallets/a.dat": {"vault_label": "password-1", "value": "hunter2!!"}}, db_path=db_path)

    statuses = latest_status_by_wallet_path(db_path=db_path)

    assert statuses["/wallets/a.dat"]["matched"] is True
    assert statuses["/wallets/a.dat"]["vault_label"] == "password-1"


def test_latest_status_by_wallet_path_reflects_unmatched_row(tmp_path):
    db_path = tmp_path / "auto_unlock_history.db"
    record_auto_unlock_run({"/wallets/a.dat": {"vault_label": None, "value": None}}, db_path=db_path)

    statuses = latest_status_by_wallet_path(db_path=db_path)

    assert statuses["/wallets/a.dat"]["matched"] is False
    assert statuses["/wallets/a.dat"]["vault_label"] is None


def test_latest_status_by_wallet_path_missing_wallet_absent_from_dict(tmp_path):
    db_path = tmp_path / "auto_unlock_history.db"
    record_auto_unlock_run({"/wallets/a.dat": {"vault_label": None, "value": None}}, db_path=db_path)

    statuses = latest_status_by_wallet_path(db_path=db_path)

    assert "/wallets/never-tried.dat" not in statuses


def test_latest_status_by_wallet_path_uses_the_most_recent_run_for_that_wallet(tmp_path):
    """
    A wallet tried, failed, tried again later and succeeded -- the badge
    must reflect the LATEST outcome, not an earlier failed attempt.
    """
    db_path = tmp_path / "auto_unlock_history.db"
    record_auto_unlock_run({"/wallets/a.dat": {"vault_label": None, "value": None}}, db_path=db_path)
    time.sleep(0.01)
    record_auto_unlock_run({"/wallets/a.dat": {"vault_label": "password-1", "value": "hunter2!!"}}, db_path=db_path)

    statuses = latest_status_by_wallet_path(db_path=db_path)

    assert statuses["/wallets/a.dat"]["matched"] is True
    assert statuses["/wallets/a.dat"]["vault_label"] == "password-1"
