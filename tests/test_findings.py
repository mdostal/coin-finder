import sqlite3
import time

from web.findings import archive, archive_all_zero_balance, clear_all_findings, list_findings, record_finding, set_watched, unarchive


def test_record_finding_then_list_includes_it(tmp_path):
    db_path = tmp_path / "findings.db"

    record_finding("Bitcoin", "1abc", 0.5, source_path="/wallet.dat", source_label="test scan", db_path=db_path)

    findings = list_findings(db_path=db_path)
    assert len(findings) == 1
    assert findings[0]["coin"] == "Bitcoin"
    assert findings[0]["address"] == "1abc"
    assert findings[0]["balance"] == 0.5
    assert findings[0]["source_path"] == "/wallet.dat"
    assert findings[0]["status"] == "new"


def test_record_finding_upserts_balance_but_keeps_first_seen(tmp_path):
    db_path = tmp_path / "findings.db"

    record_finding("Bitcoin", "1abc", 0.0, db_path=db_path)
    first = list_findings(db_path=db_path)[0]

    time.sleep(0.01)
    record_finding("Bitcoin", "1abc", 1.5, db_path=db_path)
    second = list_findings(db_path=db_path)[0]

    assert second["balance"] == 1.5
    assert second["first_seen_at"] == first["first_seen_at"]
    assert second["last_checked_at"] > first["last_checked_at"]


def test_record_finding_preserves_inconclusive_none_balance(tmp_path):
    db_path = tmp_path / "findings.db"
    record_finding("Bitcoin", "1abc", None, db_path=db_path)
    findings = list_findings(db_path=db_path)
    assert findings[0]["balance"] is None


def test_archive_and_unarchive(tmp_path):
    db_path = tmp_path / "findings.db"
    record_finding("Bitcoin", "1abc", 0.0, db_path=db_path)

    archive("Bitcoin", "1abc", db_path=db_path)
    assert list_findings(db_path=db_path) == []
    assert list_findings(include_archived=True, db_path=db_path)[0]["status"] == "archived"

    unarchive("Bitcoin", "1abc", db_path=db_path)
    assert list_findings(db_path=db_path)[0]["status"] == "new"


def test_rescan_does_not_undo_archived_status(tmp_path):
    db_path = tmp_path / "findings.db"
    record_finding("Bitcoin", "1abc", 0.0, db_path=db_path)
    archive("Bitcoin", "1abc", db_path=db_path)

    record_finding("Bitcoin", "1abc", 0.0, db_path=db_path)

    assert list_findings(db_path=db_path) == []
    assert list_findings(include_archived=True, db_path=db_path)[0]["status"] == "archived"


def test_archive_all_zero_balance_only_touches_zero_balance_new_findings(tmp_path):
    db_path = tmp_path / "findings.db"
    record_finding("Bitcoin", "1zero", 0.0, db_path=db_path)
    record_finding("Bitcoin", "1nonzero", 1.5, db_path=db_path)
    record_finding("Bitcoin", "1inconclusive", None, db_path=db_path)

    archive_all_zero_balance(db_path=db_path)

    remaining = {f["address"] for f in list_findings(db_path=db_path)}
    assert remaining == {"1nonzero", "1inconclusive"}


def test_set_watched_stores_note_and_sorts_to_top(tmp_path):
    db_path = tmp_path / "findings.db"
    record_finding("Bitcoin", "1old", 0.0, db_path=db_path)
    time.sleep(0.01)
    record_finding("Bitcoin", "1newer", 0.0, db_path=db_path)

    set_watched("Bitcoin", "1old", True, note="suspected mining-wallet chain", db_path=db_path)

    findings = list_findings(db_path=db_path)
    assert findings[0]["address"] == "1old"
    assert findings[0]["watched"] == 1
    assert findings[0]["watch_note"] == "suspected mining-wallet chain"
    assert findings[1]["watched"] == 0


def test_set_watched_false_clears_the_flag(tmp_path):
    db_path = tmp_path / "findings.db"
    record_finding("Bitcoin", "1abc", 0.0, db_path=db_path)
    set_watched("Bitcoin", "1abc", True, note="checking this out", db_path=db_path)

    set_watched("Bitcoin", "1abc", False, db_path=db_path)

    assert list_findings(db_path=db_path)[0]["watched"] == 0


def test_clear_all_findings_deletes_everything_including_watched_and_archived(tmp_path):
    db_path = tmp_path / "findings.db"
    record_finding("Bitcoin", "1a", 0.0, db_path=db_path)
    record_finding("Bitcoin", "1b", 0.0, db_path=db_path)
    archive("Bitcoin", "1b", db_path=db_path)
    set_watched("Bitcoin", "1a", True, note="important", db_path=db_path)

    clear_all_findings(db_path=db_path)

    assert list_findings(include_archived=True, db_path=db_path) == []


def test_migration_adds_watched_columns_to_a_pre_existing_db(tmp_path):
    """A findings.db created before the watched/watch_note columns existed
    must not break -- _connect() must migrate it in place, not require a
    fresh db."""
    db_path = tmp_path / "findings.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE findings (
            coin TEXT NOT NULL, address TEXT NOT NULL, balance REAL,
            source_path TEXT, source_label TEXT, status TEXT NOT NULL DEFAULT 'new',
            first_seen_at REAL NOT NULL, last_checked_at REAL NOT NULL,
            PRIMARY KEY (coin, address)
        )
        """
    )
    conn.execute(
        "INSERT INTO findings VALUES ('Bitcoin', '1old', 0.0, NULL, NULL, 'new', 0, 0)"
    )
    conn.commit()
    conn.close()

    findings = list_findings(db_path=db_path)
    assert findings[0]["watched"] == 0
    assert findings[0]["watch_note"] == ""

    set_watched("Bitcoin", "1old", True, note="works after migration", db_path=db_path)
    assert list_findings(db_path=db_path)[0]["watch_note"] == "works after migration"
