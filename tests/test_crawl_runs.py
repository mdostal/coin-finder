import sqlite3
import time

from web.crawl_runs import (
    clear_all_crawl_runs,
    find_overlap_addresses,
    list_crawl_runs,
    record_crawl_run,
)

SAMPLE_RESULTS = {
    "1seed": {"confidence": "seed", "generation": 0, "balance": 0.5, "last_activity_timestamp": 1000, "dormant_years": 5.0},
    "1cospend": {"confidence": "co-spend", "generation": 1, "balance": 0.1, "last_activity_timestamp": 900, "dormant_years": 6.0},
}


def test_record_crawl_run_then_list_includes_it(tmp_path):
    db_path = tmp_path / "crawl_runs.db"

    record_crawl_run(["1seed"], SAMPLE_RESULTS, db_path=db_path)

    runs = list_crawl_runs(db_path=db_path)
    assert len(runs) == 1
    assert runs[0]["seed_addresses"] == ["1seed"]
    assert runs[0]["address_count"] == 2


def test_list_crawl_runs_newest_first(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1old"], {"1old": {"confidence": "seed", "generation": 0, "balance": 0.0, "last_activity_timestamp": None, "dormant_years": None}}, db_path=db_path)
    time.sleep(0.01)
    record_crawl_run(["1new"], {"1new": {"confidence": "seed", "generation": 0, "balance": 0.0, "last_activity_timestamp": None, "dormant_years": None}}, db_path=db_path)

    runs = list_crawl_runs(db_path=db_path)
    assert runs[0]["seed_addresses"] == ["1new"]
    assert runs[1]["seed_addresses"] == ["1old"]


def test_record_crawl_run_persists_per_address_fields(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1seed"], SAMPLE_RESULTS, db_path=db_path)

    # No public getter for raw run_addresses rows other than find_overlap_addresses
    # (which requires >1 run) -- verify directly via a second run sharing an address.
    record_crawl_run(["1other"], {"1cospend": SAMPLE_RESULTS["1cospend"]}, db_path=db_path)

    overlaps = find_overlap_addresses(db_path=db_path)
    assert "1cospend" in overlaps
    entry = overlaps["1cospend"]["runs"][0]
    assert entry["confidence"] == "co-spend"
    assert entry["generation"] == 1


def test_find_overlap_addresses_empty_with_zero_or_one_run(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    assert find_overlap_addresses(db_path=db_path) == {}

    record_crawl_run(["1seed"], SAMPLE_RESULTS, db_path=db_path)
    assert find_overlap_addresses(db_path=db_path) == {}


def test_find_overlap_addresses_finds_address_shared_across_runs(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1walletA"], {"1shared": {"confidence": "co-spend", "generation": 1, "balance": 2.0, "last_activity_timestamp": None, "dormant_years": None}}, db_path=db_path)
    record_crawl_run(["1walletB"], {"1shared": {"confidence": "output", "generation": 2, "balance": 2.0, "last_activity_timestamp": None, "dormant_years": None}}, db_path=db_path)

    overlaps = find_overlap_addresses(db_path=db_path)

    assert set(overlaps.keys()) == {"1shared"}
    assert len(overlaps["1shared"]["runs"]) == 2
    seeds_seen = {tuple(r["seed_addresses"]) for r in overlaps["1shared"]["runs"]}
    assert seeds_seen == {("1walletA",), ("1walletB",)}


def test_find_overlap_addresses_ignores_addresses_seen_in_only_one_run(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1walletA"], SAMPLE_RESULTS, db_path=db_path)
    record_crawl_run(["1walletB"], {"1unrelated": {"confidence": "seed", "generation": 0, "balance": 0.0, "last_activity_timestamp": None, "dormant_years": None}}, db_path=db_path)

    overlaps = find_overlap_addresses(db_path=db_path)

    assert overlaps == {}


def test_clear_all_crawl_runs_deletes_everything(tmp_path):
    db_path = tmp_path / "crawl_runs.db"
    record_crawl_run(["1seed"], SAMPLE_RESULTS, db_path=db_path)

    clear_all_crawl_runs(db_path=db_path)

    assert list_crawl_runs(db_path=db_path) == []
    assert find_overlap_addresses(db_path=db_path) == {}


def test_connect_creates_parent_directory(tmp_path):
    db_path = tmp_path / "nested" / "dir" / "crawl_runs.db"
    record_crawl_run(["1seed"], SAMPLE_RESULTS, db_path=db_path)
    assert db_path.exists()


def test_migration_does_not_crash_on_pre_existing_schema_less_db(tmp_path):
    """A crawl_runs.db that only has the `runs` table (simulating a future
    schema addition landing on an older db) must not crash -- same
    ALTER TABLE + OperationalError-catch discipline as web/findings.py."""
    db_path = tmp_path / "crawl_runs.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE runs (run_id INTEGER PRIMARY KEY AUTOINCREMENT, seed_addresses TEXT NOT NULL, created_at REAL NOT NULL)")
    conn.commit()
    conn.close()

    # Should not raise even though run_addresses doesn't exist yet.
    record_crawl_run(["1seed"], SAMPLE_RESULTS, db_path=db_path)
    assert list_crawl_runs(db_path=db_path)[0]["address_count"] == 2
