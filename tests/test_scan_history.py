import sqlite3
import time

from web.scan_history import clear_scan_history, list_scan_history, record_scan


def test_record_scan_then_list_includes_it(tmp_path):
    db_path = tmp_path / "scan_history.db"

    record_scan("/data/drive1", "/ui_output/drive1", 3, db_path=db_path)

    scans = list_scan_history(db_path=db_path)
    assert len(scans) == 1
    assert scans[0]["input_dir"] == "/data/drive1"
    assert scans[0]["output_dir"] == "/ui_output/drive1"
    assert scans[0]["files_found"] == 3


def test_list_scan_history_newest_first(tmp_path):
    db_path = tmp_path / "scan_history.db"
    record_scan("/data/old", "/ui_output/old", 1, db_path=db_path)
    time.sleep(0.01)
    record_scan("/data/new", "/ui_output/new", 2, db_path=db_path)

    scans = list_scan_history(db_path=db_path)
    assert scans[0]["output_dir"] == "/ui_output/new"
    assert scans[1]["output_dir"] == "/ui_output/old"


def test_clear_scan_history_deletes_everything(tmp_path):
    db_path = tmp_path / "scan_history.db"
    record_scan("/data/drive1", "/ui_output/drive1", 3, db_path=db_path)

    clear_scan_history(db_path=db_path)

    assert list_scan_history(db_path=db_path) == []


def test_connect_creates_parent_directory(tmp_path):
    db_path = tmp_path / "nested" / "dir" / "scan_history.db"
    record_scan("/data/drive1", "/ui_output/drive1", 1, db_path=db_path)
    assert db_path.exists()


def test_migration_does_not_crash_on_pre_existing_schema_less_db(tmp_path):
    """A scan_history.db that predates a future column addition must not
    crash -- same ALTER TABLE + OperationalError-catch discipline as
    web/findings.py and web/crawl_runs.py."""
    db_path = tmp_path / "scan_history.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE scans (output_dir TEXT PRIMARY KEY, input_dir TEXT NOT NULL, files_found INTEGER NOT NULL, created_at REAL NOT NULL)"
    )
    conn.commit()
    conn.close()

    record_scan("/data/drive1", "/ui_output/drive1", 1, db_path=db_path)
    assert list_scan_history(db_path=db_path)[0]["output_dir"] == "/ui_output/drive1"
