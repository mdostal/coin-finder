import time

from web.findings import archive, archive_all_zero_balance, list_findings, record_finding, unarchive


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
